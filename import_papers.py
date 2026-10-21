#!/usr/bin/env python3
"""Import papers into Zotero from DOIs or titles via CrossRef/OpenAlex APIs.

All metadata comes from academic APIs — never from LLM generation.

Usage:
    # Import by DOI (most reliable)
    python import_papers.py --doi 10.34133/2020/7481687

    # Import multiple DOIs from a file (one DOI per line)
    python import_papers.py --file dois.txt

    # Search by title and confirm before importing
    python import_papers.py --search "plant growth dynamics phenotyping"

    # Specify target collection
    python import_papers.py --doi 10.34133/2020/7481687 --collection Z3K94YXB

    # Add tags during import
    python import_papers.py --doi 10.34133/2020/7481687 --tags growth-modeling,time-series

    # Download PDF alongside metadata import
    python import_papers.py --doi 10.34133/2020/7481687 --pdf

    # Download PDF to a specific directory
    python import_papers.py --doi 10.34133/2020/7481687 --pdf --pdf-dir /path/to/pdfs

    # Dry run (preview without importing)
    python import_papers.py --file dois.txt --pdf --dry-run
"""

import argparse
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from pyzotero import zotero

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("ZOTERO_API_KEY")
LIBRARY_ID = os.getenv("ZOTERO_LIBRARY_ID")
LIBRARY_TYPE = os.getenv("ZOTERO_LIBRARY_TYPE", "user")

# Polite pool: CrossRef asks for an email for priority access
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "")

USER_AGENT = "ZoteroAIAgent/1.0 (https://github.com/user/zotero-ai-agent)"


def _zot():
    if not API_KEY or not LIBRARY_ID:
        sys.exit("Error: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")
    return zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)


# ---------------------------------------------------------------------------
# CrossRef API
# ---------------------------------------------------------------------------


def _http_get_json(url):
    """Simple HTTP GET returning parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def crossref_by_doi(doi):
    """Fetch metadata from CrossRef by DOI."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    if CROSSREF_EMAIL:
        url += f"?mailto={CROSSREF_EMAIL}"
    data = _http_get_json(url)
    if data and data.get("status") == "ok":
        return data["message"]
    return None


def crossref_search(query, rows=5):
    """Search CrossRef by title query. Returns list of work items."""
    params = urllib.parse.urlencode({"query": query, "rows": rows})
    url = f"https://api.crossref.org/works?{params}"
    if CROSSREF_EMAIL:
        url += f"&mailto={CROSSREF_EMAIL}"
    data = _http_get_json(url)
    if data and data.get("status") == "ok":
        return data["message"].get("items", [])
    return []


def openalex_search(query, per_page=5):
    """Search OpenAlex as fallback when CrossRef doesn't find results."""
    params = urllib.parse.urlencode({
        "search": query,
        "per_page": per_page,
        "select": "id,doi,title,authorships,publication_year,primary_location,type",
    })
    url = f"https://api.openalex.org/works?{params}"
    if CROSSREF_EMAIL:
        url += f"&mailto={CROSSREF_EMAIL}"
    data = _http_get_json(url)
    if data:
        return data.get("results", [])
    return []


# ---------------------------------------------------------------------------
# Metadata mapping: CrossRef → Zotero
# ---------------------------------------------------------------------------


def crossref_to_zotero(cr):
    """Convert CrossRef work item to Zotero item dict."""
    # Determine item type
    cr_type = cr.get("type", "journal-article")
    type_map = {
        "journal-article": "journalArticle",
        "book": "book",
        "book-chapter": "bookSection",
        "proceedings-article": "conferencePaper",
        "posted-content": "preprint",
        "report": "report",
        "dissertation": "thesis",
    }
    item_type = type_map.get(cr_type, "journalArticle")

    # Title
    titles = cr.get("title", [])
    title = titles[0] if titles else "(no title)"

    # Authors
    creators = []
    for author in cr.get("author", []):
        creators.append({
            "creatorType": "author",
            "firstName": author.get("given", ""),
            "lastName": author.get("family", ""),
        })

    # Date
    date_parts = cr.get("published", cr.get("issued", {})).get("date-parts", [[]])
    date_arr = date_parts[0] if date_parts else []
    if len(date_arr) >= 3:
        date = f"{date_arr[0]}-{date_arr[1]:02d}-{date_arr[2]:02d}"
    elif len(date_arr) >= 2:
        date = f"{date_arr[0]}-{date_arr[1]:02d}"
    elif len(date_arr) >= 1:
        date = str(date_arr[0])
    else:
        date = ""

    # Journal
    container = cr.get("container-title", [])
    journal = container[0] if container else ""

    # DOI
    doi = cr.get("DOI", "")

    # Abstract
    abstract = cr.get("abstract", "")
    # CrossRef abstracts may contain JATS XML tags, strip them
    if abstract:
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    # Volume, issue, pages
    volume = cr.get("volume", "")
    issue = cr.get("issue", "")
    pages = cr.get("page", "")

    # ISSN
    issns = cr.get("ISSN", [])
    issn = issns[0] if issns else ""

    # URL
    url = cr.get("URL", "")
    if not url and doi:
        url = f"https://doi.org/{doi}"

    item = {
        "itemType": item_type,
        "title": title,
        "creators": creators,
        "date": date,
        "DOI": doi,
        "url": url,
        "abstractNote": abstract,
        "publicationTitle": journal,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "ISSN": issn,
    }

    return item


def openalex_to_crossref_doi(oa_result):
    """Extract DOI from OpenAlex result for CrossRef lookup."""
    doi = oa_result.get("doi", "")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    return doi


# ---------------------------------------------------------------------------
# PDF download (multi-source fallback chain)
# ---------------------------------------------------------------------------

# Minimum / maximum PDF file size for validation
PDF_MIN_SIZE = 50_000       # 50 KB — smaller is likely an error page
PDF_MAX_SIZE = 100_000_000  # 100 MB — larger is likely a dataset/supplement bundle

# Default PDF output directory
DEFAULT_PDF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "OV-Papers", "PDF-raw",
)


def _generate_citekey(item_data):
    """Generate a citekey in {firstauthor}{year}{firstword} format."""
    creators = item_data.get("creators", [])
    if creators:
        last = creators[0].get("lastName", "unknown").lower()
        # Remove non-ascii for safe filenames
        last = re.sub(r"[^a-z]", "", last)
    else:
        last = "unknown"

    date = item_data.get("date", "")
    year = re.search(r"(\d{4})", date)
    year = year.group(1) if year else "0000"

    title = item_data.get("title", "")
    # First meaningful word from title (skip articles/prepositions)
    # Treat hyphenated words as one (e.g., "Time-Series" → "timeseries")
    skip = {"a", "an", "the", "of", "in", "on", "for", "and", "to", "with", "from", "by"}
    words = re.findall(r"[a-zA-Z]+(?:-[a-zA-Z]+)*", title)
    first_word = "unknown"
    for w in words:
        base = w.split("-")[0].lower()
        if base not in skip:
            first_word = w.replace("-", "").lower()
            break

    return f"{last}{year}{first_word}"


def _http_download(url, timeout=30):
    """Download binary content from URL. Returns (bytes, content_type) or (None, None)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            data = resp.read()
            return data, ct
    except Exception as e:
        print(f"    Download error: {e}")
        return None, None


def _validate_pdf(data, source_label=""):
    """Validate that data is a real PDF. Returns (ok, reason)."""
    if not data:
        return False, "empty response"
    if not data[:5].startswith(b"%PDF"):
        return False, "not a PDF (magic bytes mismatch)"
    if len(data) < PDF_MIN_SIZE:
        return False, f"too small ({len(data)} bytes) — likely an error page"
    if len(data) > PDF_MAX_SIZE:
        return False, f"too large ({len(data) // 1_000_000} MB) — likely a supplement bundle"
    return True, "ok"


def _try_unpaywall(doi, email):
    """Source 1: Unpaywall API — returns direct PDF URL or None."""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}?email={email}"
    data = _http_get_json(url)
    if not data or data.get("error"):
        return None
    best = data.get("best_oa_location") or {}
    pdf_url = best.get("url_for_pdf")
    if pdf_url:
        return pdf_url
    # Check all OA locations
    for loc in data.get("oa_locations", []):
        if loc.get("url_for_pdf"):
            return loc["url_for_pdf"]
    return None


def _try_semantic_scholar(doi):
    """Source 2: Semantic Scholar — returns PDF URL if it's a real PDF link."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='/')}?fields=openAccessPdf,externalIds"
    data = _http_get_json(url)
    if not data:
        return None, None
    pdf_info = data.get("openAccessPdf") or {}
    pdf_url = pdf_info.get("url", "")
    # Reject if it's just a DOI URL (not a direct PDF)
    if pdf_url and "doi.org/" not in pdf_url:
        return pdf_url, None
    # Extract PMC ID for later use
    ext = data.get("externalIds") or {}
    pmcid = ext.get("PubMedCentral")
    return None, pmcid


def _try_europepmc(doi):
    """Source 3: Europe PMC — returns PDF URL from fullTextUrlList."""
    encoded = urllib.parse.quote(f"DOI:{doi}", safe="")
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={encoded}&format=json&resultType=core&pageSize=1"
    data = _http_get_json(url)
    if not data:
        return None, None
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return None, None
    r = results[0]
    pmcid = r.get("pmcid")
    urls = r.get("fullTextUrlList", {}).get("fullTextUrl", [])
    for u in urls:
        if u.get("documentStyle") == "pdf" and u.get("availabilityCode") == "OA":
            return u["url"], pmcid
    return None, pmcid


def _try_pmc_oa(pmcid):
    """Source 4: PMC OA API — download tar.gz, extract PDF."""
    if not pmcid:
        return None
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_text = resp.read().decode("utf-8")
    except Exception:
        return None

    # Parse XML to find tgz link
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    tgz_url = None
    for link in root.iter("link"):
        if link.get("format") == "tgz":
            tgz_url = link.get("href", "")
            break
    if not tgz_url:
        return None

    # Convert ftp:// to https://
    tgz_url = tgz_url.replace("ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov")

    print(f"    Downloading PMC package ({pmcid})...")
    tgz_data, _ = _http_download(tgz_url, timeout=120)
    if not tgz_data:
        return None

    # Extract PDF from tar.gz
    try:
        with tarfile.open(fileobj=io.BytesIO(tgz_data), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".pdf"):
                    f = tar.extractfile(member)
                    if f:
                        return f.read()
    except Exception as e:
        print(f"    tar.gz extraction error: {e}")
    return None


def find_and_download_pdf(doi, email="unpaywall@example.org"):
    """Try multiple sources to find and download a PDF. Returns (bytes, source) or (None, None)."""
    sources = []

    # Source 1: Unpaywall
    print("    Trying Unpaywall...", end="")
    pdf_url = _try_unpaywall(doi, email)
    if pdf_url:
        print(f" found: {pdf_url[:80]}")
        data, _ = _http_download(pdf_url)
        ok, reason = _validate_pdf(data, "Unpaywall")
        if ok:
            return data, f"Unpaywall ({pdf_url[:80]})"
        print(f"    Unpaywall PDF invalid: {reason}")
    else:
        print(" no direct PDF link")

    # Source 2: Semantic Scholar
    print("    Trying Semantic Scholar...", end="")
    pdf_url, pmcid_s2 = _try_semantic_scholar(doi)
    if pdf_url:
        print(f" found: {pdf_url[:80]}")
        data, _ = _http_download(pdf_url)
        ok, reason = _validate_pdf(data, "S2")
        if ok:
            return data, f"Semantic Scholar ({pdf_url[:80]})"
        print(f"    S2 PDF invalid: {reason}")
    else:
        print(" no direct PDF link")

    # Source 3: Europe PMC
    print("    Trying Europe PMC...", end="")
    pdf_url, pmcid_epmc = _try_europepmc(doi)
    pmcid = pmcid_s2 or pmcid_epmc
    if pdf_url:
        print(f" found: {pdf_url[:80]}")
        data, _ = _http_download(pdf_url)
        ok, reason = _validate_pdf(data, "EuropePMC")
        if ok:
            return data, f"Europe PMC ({pdf_url[:80]})"
        print(f"    Europe PMC PDF invalid: {reason}")
    else:
        print(" no direct PDF link")

    # Source 4: PMC OA tar.gz
    if pmcid:
        print(f"    Trying PMC OA package ({pmcid})...")
        data = _try_pmc_oa(pmcid)
        ok, reason = _validate_pdf(data, "PMC-OA")
        if ok:
            return data, f"PMC OA ({pmcid})"
        if data:
            print(f"    PMC OA PDF invalid: {reason}")
    else:
        print("    No PMC ID available, skipping PMC OA")

    return None, None


def download_pdf_for_item(item_data, pdf_dir=None, dry_run=False):
    """Download PDF for an item. Returns the saved filepath or None."""
    doi = item_data.get("DOI", "")
    if not doi:
        print("  PDF: no DOI, skipping PDF download")
        return None

    citekey = _generate_citekey(item_data)
    out_dir = pdf_dir or DEFAULT_PDF_DIR
    out_path = os.path.join(out_dir, f"{citekey}.pdf")

    # Check if already exists
    if os.path.exists(out_path):
        print(f"  PDF: already exists: {citekey}.pdf")
        return out_path

    email = CROSSREF_EMAIL or "unpaywall@example.org"

    if dry_run:
        print(f"  [DRY RUN] Would attempt PDF download for: {citekey}")
        print(f"            DOI: {doi}")
        # Still probe sources to show what would happen
        pdf_url = _try_unpaywall(doi, email)
        if pdf_url:
            print(f"            Unpaywall PDF: {pdf_url[:80]}")
        else:
            _, pmcid_s2 = _try_semantic_scholar(doi)
            pdf_url_epmc, pmcid_epmc = _try_europepmc(doi)
            pmcid = pmcid_s2 or pmcid_epmc
            if pdf_url_epmc:
                print(f"            Europe PMC PDF: {pdf_url_epmc[:80]}")
            elif pmcid:
                print(f"            PMC OA package available: {pmcid}")
            else:
                print(f"            No OA PDF source found")
        return None

    print(f"  PDF: searching OA sources for {citekey}...")
    data, source = find_and_download_pdf(doi, email)
    if not data:
        print(f"  PDF: no OA PDF found for {doi}")
        return None

    # Save
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    size_mb = len(data) / 1_000_000
    print(f"  PDF: saved {citekey}.pdf ({size_mb:.1f} MB) from {source}")
    return out_path


# ---------------------------------------------------------------------------
# Zotero import
# ---------------------------------------------------------------------------


def check_duplicate(zot, doi=None, title=None):
    """Check if a paper already exists in the library."""
    if doi:
        results = zot.top(q=doi)
        for r in results:
            if r["data"].get("DOI", "").lower() == doi.lower():
                return r
    if title:
        results = zot.top(q=title[:50])
        for r in results:
            if title.lower()[:40] in r["data"].get("title", "").lower():
                return r
    return None


def import_item(zot, item_data, collection_key=None, tags=None, dry_run=False,
                download_pdf=False, pdf_dir=None):
    """Import a single item into Zotero."""
    title = item_data.get("title", "(no title)")
    doi = item_data.get("DOI", "")

    # Check duplicate
    existing = check_duplicate(zot, doi=doi, title=title)
    if existing:
        ekey = existing["data"]["key"]
        print(f"  SKIP (duplicate): [{ekey}] {title[:60]}")
        # Still try PDF if requested and item exists
        if download_pdf:
            download_pdf_for_item(item_data, pdf_dir, dry_run)
        return None

    # Add collection
    if collection_key:
        item_data["collections"] = [collection_key]

    # Add tags
    if tags:
        item_data["tags"] = [{"tag": t} for t in tags]

    if dry_run:
        authors = "; ".join(
            c.get("lastName", "") for c in item_data.get("creators", [])
        )[:40]
        print(f"  [DRY RUN] Would import: {authors} — {title[:60]}")
        print(f"            DOI: {doi}")
        if download_pdf:
            download_pdf_for_item(item_data, pdf_dir, dry_run=True)
        return None

    # Create in Zotero
    template = zot.item_template(item_data["itemType"])
    for k, v in item_data.items():
        if k in template:
            template[k] = v
    # Handle fields not in template
    for k in ("collections", "tags"):
        if k in item_data:
            template[k] = item_data[k]

    resp = zot.create_items([template])
    if resp.get("successful"):
        for idx, created in resp["successful"].items():
            key = created["data"]["key"]
            print(f"  IMPORTED: [{key}] {title[:60]}")
            if download_pdf:
                download_pdf_for_item(item_data, pdf_dir, dry_run=False)
            return created
    else:
        failed = resp.get("failed", {})
        print(f"  FAILED: {title[:60]}")
        for idx, err in failed.items():
            print(f"    Error: {err}")
        return None


# ---------------------------------------------------------------------------
# Main workflows
# ---------------------------------------------------------------------------


def import_by_doi(doi, zot, collection_key=None, tags=None, dry_run=False,
                   download_pdf=False, pdf_dir=None):
    """Import a single paper by DOI."""
    print(f"\nLooking up DOI: {doi}")
    cr = crossref_by_doi(doi)
    if not cr:
        print(f"  NOT FOUND on CrossRef: {doi}")
        return None
    item_data = crossref_to_zotero(cr)
    return import_item(zot, item_data, collection_key, tags, dry_run,
                       download_pdf, pdf_dir)


def import_from_file(filepath, zot, collection_key=None, tags=None, dry_run=False,
                     download_pdf=False, pdf_dir=None):
    """Import papers from a file of DOIs (one per line)."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"Found {len(lines)} DOIs in {filepath}")
    imported = 0
    skipped = 0
    failed = 0

    for i, doi in enumerate(lines, 1):
        print(f"\n[{i}/{len(lines)}] {doi}")
        cr = crossref_by_doi(doi)
        if not cr:
            print(f"  NOT FOUND on CrossRef")
            failed += 1
            continue
        item_data = crossref_to_zotero(cr)
        result = import_item(zot, item_data, collection_key, tags, dry_run,
                             download_pdf, pdf_dir)
        if result:
            imported += 1
        elif result is None and not dry_run:
            skipped += 1
        # Rate limiting: be polite to CrossRef
        if i < len(lines):
            time.sleep(0.5)

    print(f"\nDone: {imported} imported, {skipped} skipped (duplicate), {failed} failed")


def search_and_import(query, zot, collection_key=None, tags=None, dry_run=False,
                      download_pdf=False, pdf_dir=None):
    """Search by title, show results, and let user choose which to import."""
    print(f"\nSearching CrossRef for: {query}")
    results = crossref_search(query, rows=5)

    if not results:
        print("  No results from CrossRef. Trying OpenAlex...")
        oa_results = openalex_search(query, per_page=5)
        if not oa_results:
            print("  No results from OpenAlex either.")
            return

        # Show OpenAlex results and try to get DOIs
        print(f"\nFound {len(oa_results)} results from OpenAlex:\n")
        for i, r in enumerate(oa_results, 1):
            title = r.get("title", "(no title)")
            year = r.get("publication_year", "?")
            doi = openalex_to_crossref_doi(r)
            authors = "; ".join(
                a.get("author", {}).get("display_name", "?")
                for a in r.get("authorships", [])[:3]
            )
            print(f"  {i}. [{year}] {authors}")
            print(f"     {title}")
            print(f"     DOI: {doi or '(none)'}")
            print()

        choice = input("Enter numbers to import (e.g. 1,3) or 'q' to quit: ").strip()
        if choice.lower() == "q":
            return

        for idx_str in choice.split(","):
            idx = int(idx_str.strip()) - 1
            if 0 <= idx < len(oa_results):
                doi = openalex_to_crossref_doi(oa_results[idx])
                if doi:
                    import_by_doi(doi, zot, collection_key, tags, dry_run,
                                  download_pdf, pdf_dir)
                else:
                    print(f"  No DOI for result {idx + 1}, cannot import.")
        return

    # Show CrossRef results
    print(f"\nFound {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        titles = r.get("title", ["(no title)"])
        title = titles[0] if titles else "(no title)"
        doi = r.get("DOI", "?")
        date_parts = r.get("published", r.get("issued", {})).get("date-parts", [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else "?"
        authors = "; ".join(
            a.get("family", "?") for a in r.get("author", [])[:3]
        )
        container = r.get("container-title", [""])
        journal = container[0] if container else ""
        print(f"  {i}. [{year}] {authors}")
        print(f"     {title}")
        print(f"     {journal} | DOI: {doi}")
        print()

    choice = input("Enter numbers to import (e.g. 1,3) or 'q' to quit: ").strip()
    if choice.lower() == "q":
        return

    for idx_str in choice.split(","):
        idx = int(idx_str.strip()) - 1
        if 0 <= idx < len(results):
            item_data = crossref_to_zotero(results[idx])
            import_item(zot, item_data, collection_key, tags, dry_run,
                        download_pdf, pdf_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import papers into Zotero from DOIs or title search (via CrossRef/OpenAlex)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without importing")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--doi", help="Import a single DOI")
    source.add_argument("--file", help="Import DOIs from a file (one per line)")
    source.add_argument("--search", help="Search by title and choose results to import")

    parser.add_argument("--collection", help="Target collection key")
    parser.add_argument("--tags", help="Comma-separated tags to add (e.g. growth-modeling,time-series)")
    parser.add_argument("--pdf", action="store_true",
                        help="Download OA PDF (Unpaywall → Semantic Scholar → Europe PMC → PMC OA)")
    parser.add_argument("--pdf-dir",
                        help=f"PDF output directory (default: {DEFAULT_PDF_DIR})")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    zot = _zot()
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
    pdf_kw = {"download_pdf": args.pdf, "pdf_dir": args.pdf_dir}

    if args.doi:
        import_by_doi(args.doi, zot, args.collection, tags, args.dry_run, **pdf_kw)
    elif args.file:
        import_from_file(args.file, zot, args.collection, tags, args.dry_run, **pdf_kw)
    elif args.search:
        search_and_import(args.search, zot, args.collection, tags, args.dry_run, **pdf_kw)


if __name__ == "__main__":
    main()
