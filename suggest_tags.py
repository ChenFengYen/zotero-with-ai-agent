#!/usr/bin/env python3
"""Suggest tags for Zotero items using OpenAlex concept annotations.

All tags come from OpenAlex's concept taxonomy — never from LLM generation.

Usage:
    # Preview suggested tags for items without tags
    python suggest_tags.py --untagged --dry-run

    # Preview for a specific collection
    python suggest_tags.py --collection Z3K94YXB --dry-run

    # Preview for specific items by key
    python suggest_tags.py --keys ABC12345 DEF67890 --dry-run

    # Apply suggested tags (with confirmation per item)
    python suggest_tags.py --untagged

    # Adjust filters: min score, min concept level, max tags per item
    python suggest_tags.py --untagged --min-score 0.5 --min-level 2 --max-tags 5

    # Batch mode: show all suggestions first, confirm once to apply all
    python suggest_tags.py --untagged --batch
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from pyzotero import zotero

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("ZOTERO_API_KEY")
LIBRARY_ID = os.getenv("ZOTERO_LIBRARY_ID")
LIBRARY_TYPE = os.getenv("ZOTERO_LIBRARY_TYPE", "user")
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "")

USER_AGENT = "ZoteroAIAgent/1.0 (https://github.com/user/zotero-ai-agent)"

# Default filter thresholds
DEFAULT_MIN_SCORE = 0.4
DEFAULT_MIN_LEVEL = 2
DEFAULT_MAX_TAGS = 8


def _zot():
    if not API_KEY or not LIBRARY_ID:
        sys.exit("Error: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")
    return zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)


# ---------------------------------------------------------------------------
# OpenAlex API
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
    except Exception:
        return None


def openalex_concepts_by_doi(doi, min_score=0.4, min_level=2):
    """Fetch concept annotations from OpenAlex for a given DOI.

    Returns list of dicts: [{"name": str, "score": float, "level": int}, ...]
    Sorted by score descending.
    """
    encoded = urllib.parse.quote(doi, safe="")
    url = f"https://api.openalex.org/works/doi:{encoded}"
    if CROSSREF_EMAIL:
        url += f"?mailto={CROSSREF_EMAIL}"

    data = _http_get_json(url)
    if not data:
        return []

    concepts = []
    for c in data.get("concepts", []):
        score = c.get("score", 0)
        level = c.get("level", 0)
        if score >= min_score and level >= min_level:
            concepts.append({
                "name": c.get("display_name", ""),
                "score": score,
                "level": level,
            })

    concepts.sort(key=lambda x: x["score"], reverse=True)
    return concepts


# ---------------------------------------------------------------------------
# Tag config (loaded from tag_config.json)
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "tag_config.json"


def _load_tag_config():
    """Load tag_config.json and build TAG_MAP + SKIP_CONCEPTS.

    TAG_MAP: {OpenAlex concept name -> Zotero tag name or None}
    SKIP_CONCEPTS: set of OpenAlex concept names to always ignore
    """
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    # Build reverse map: OpenAlex concept name -> Zotero tag name
    tag_map = {}
    for tag_name, tag_info in config.get("tags", {}).items():
        for oa_name in tag_info.get("openalex", []):
            tag_map[oa_name] = tag_name

    # Build skip set from all openalex_skip groups
    skip = set()
    for group_name, items in config.get("openalex_skip", {}).items():
        if isinstance(items, list):
            skip.update(items)

    # Entries in redundant_with_mapped should map to None (explicit skip)
    for name in config.get("openalex_skip", {}).get("redundant_with_mapped", []):
        tag_map[name] = None

    return tag_map, skip


TAG_MAP, SKIP_CONCEPTS = _load_tag_config()


def map_concept_to_tag(concept_name):
    """Map an OpenAlex concept name to a Zotero tag.

    Returns None if the concept should be skipped.
    """
    if concept_name in SKIP_CONCEPTS:
        return None
    if concept_name in TAG_MAP:
        return TAG_MAP[concept_name]  # may be None (explicit skip)
    # Skip concepts with Wikidata disambiguation parentheses that aren't
    # in TAG_MAP — they are almost always the wrong sense of the word
    if "(" in concept_name:
        return None
    # Default: lowercase the concept name
    return concept_name.lower().replace(" ", "-")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def get_items_to_process(zot, args):
    """Get the list of Zotero items to suggest tags for."""
    items = []

    if args.keys:
        for key in args.keys:
            items.append(zot.item(key))
    elif args.collection:
        items = zot.collection_items(args.collection)
    elif args.untagged:
        # Fetch all items, filter to those without tags
        all_items = zot.everything(zot.top())
        items = [
            i for i in all_items
            if not i["data"].get("tags")
            and i["data"].get("itemType") not in ("attachment", "note")
        ]
    else:
        # Default: all items with DOI
        items = zot.everything(zot.top())

    # Filter to items that have a DOI (required for OpenAlex lookup)
    result = []
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") in ("attachment", "note"):
            continue
        if data.get("DOI"):
            result.append(item)

    return result


def suggest_tags_for_item(item, min_score, min_level, max_tags):
    """Query OpenAlex and return suggested tags for one item.

    Returns dict: {
        "item": item,
        "existing_tags": [...],
        "suggested_tags": [...],
        "concepts_raw": [...],
    }
    """
    data = item["data"]
    doi = data.get("DOI", "")
    existing = {t["tag"] for t in data.get("tags", [])}

    concepts = openalex_concepts_by_doi(doi, min_score=min_score, min_level=min_level)

    suggested = []
    for c in concepts:
        tag = map_concept_to_tag(c["name"])
        if tag and tag not in existing and tag not in {s["tag"] for s in suggested}:
            suggested.append({
                "tag": tag,
                "source_concept": c["name"],
                "score": c["score"],
                "level": c["level"],
            })

    # Limit to max_tags
    suggested = suggested[:max_tags]

    return {
        "item": item,
        "existing_tags": sorted(existing),
        "suggested_tags": suggested,
        "concepts_raw": concepts,
    }


def print_suggestion(result, index=None):
    """Print a single item's tag suggestion."""
    data = result["item"]["data"]
    key = data["key"]
    title = data.get("title", "(no title)")
    doi = data.get("DOI", "")
    existing = result["existing_tags"]
    suggested = result["suggested_tags"]

    prefix = f"[{index}] " if index is not None else ""
    print(f"\n{prefix}[{key}] {title[:70]}")
    print(f"  DOI: {doi}")
    if existing:
        print(f"  Existing tags: {', '.join(existing)}")
    else:
        print(f"  Existing tags: (none)")

    if suggested:
        print(f"  Suggested tags:")
        for s in suggested:
            print(f"    + {s['tag']:30s}  (from: {s['source_concept']}, "
                  f"score={s['score']:.2f}, L{s['level']})")
    else:
        print(f"  No new tags to suggest.")


def apply_tags(zot, item, tags):
    """Add tags to an item in Zotero."""
    item["data"]["tags"].extend({"tag": t} for t in tags)
    zot.update_item(item)


# ---------------------------------------------------------------------------
# Main workflows
# ---------------------------------------------------------------------------


def run_interactive(zot, items, min_score, min_level, max_tags, dry_run):
    """Process items one by one with confirmation."""
    total = len(items)
    applied = 0
    skipped = 0

    for i, item in enumerate(items, 1):
        print(f"\n{'=' * 60}")
        print(f"Item {i}/{total}")

        result = suggest_tags_for_item(item, min_score, min_level, max_tags)
        print_suggestion(result)

        suggested = result["suggested_tags"]
        if not suggested:
            skipped += 1
            continue

        if dry_run:
            skipped += 1
            continue

        choice = input("\n  Apply these tags? [y/n/e(dit)/q(uit)] ").strip().lower()
        if choice == "q":
            print("Quitting.")
            break
        elif choice == "y":
            tags = [s["tag"] for s in suggested]
            apply_tags(zot, item, tags)
            print(f"  Applied {len(tags)} tags.")
            applied += 1
        elif choice == "e":
            # Let user pick which tags to apply
            indices = input("  Enter tag numbers to apply (e.g. 1,3,5): ").strip()
            if indices:
                selected = []
                for idx_str in indices.split(","):
                    try:
                        idx = int(idx_str.strip()) - 1
                        if 0 <= idx < len(suggested):
                            selected.append(suggested[idx]["tag"])
                    except ValueError:
                        pass
                if selected:
                    apply_tags(zot, item, selected)
                    print(f"  Applied {len(selected)} tags: {', '.join(selected)}")
                    applied += 1
                else:
                    skipped += 1
        else:
            skipped += 1

        # Rate limiting for OpenAlex
        if i < total:
            time.sleep(0.3)

    print(f"\nDone: {applied} items tagged, {skipped} skipped, "
          f"{total - applied - skipped} remaining")


def run_batch(zot, items, min_score, min_level, max_tags, dry_run):
    """Show all suggestions first, then confirm once to apply all."""
    total = len(items)
    results = []

    print(f"Fetching OpenAlex concepts for {total} items...")

    for i, item in enumerate(items, 1):
        result = suggest_tags_for_item(item, min_score, min_level, max_tags)
        if result["suggested_tags"]:
            results.append(result)
            print_suggestion(result, index=len(results))
        else:
            data = item["data"]
            print(f"\n  [{data['key']}] {data.get('title', '')[:50]} — no suggestions")

        # Rate limiting
        if i < total:
            time.sleep(0.3)

    if not results:
        print("\nNo tags to suggest for any item.")
        return

    print(f"\n{'=' * 60}")
    print(f"Summary: {len(results)} items with suggestions out of {total} total")

    if dry_run:
        print("(Dry run — no changes made)")
        return

    choice = input("\nApply all suggested tags? [y/n] ").strip().lower()
    if choice == "y":
        for result in results:
            tags = [s["tag"] for s in result["suggested_tags"]]
            apply_tags(zot, result["item"], tags)
            title = result["item"]["data"].get("title", "")[:40]
            print(f"  Tagged [{result['item']['data']['key']}] +{len(tags)} tags")
        print(f"\nApplied tags to {len(results)} items.")
    else:
        print("No changes made.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Suggest tags for Zotero items using OpenAlex concept annotations"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview suggestions without applying")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--untagged", action="store_true",
                        help="Process items without any tags")
    source.add_argument("--collection", help="Process items in a collection")
    source.add_argument("--keys", nargs="+", help="Process specific item keys")

    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"Minimum concept score (default: {DEFAULT_MIN_SCORE})")
    parser.add_argument("--min-level", type=int, default=DEFAULT_MIN_LEVEL,
                        help=f"Minimum concept level (default: {DEFAULT_MIN_LEVEL})")
    parser.add_argument("--max-tags", type=int, default=DEFAULT_MAX_TAGS,
                        help=f"Max tags per item (default: {DEFAULT_MAX_TAGS})")
    parser.add_argument("--batch", action="store_true",
                        help="Show all suggestions first, confirm once to apply")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    zot = _zot()

    items = get_items_to_process(zot, args)
    if not items:
        print("No items with DOI found matching your criteria.")
        return

    print(f"Found {len(items)} items to process.")

    if args.batch:
        run_batch(zot, items, args.min_score, args.min_level, args.max_tags, args.dry_run)
    else:
        run_interactive(zot, items, args.min_score, args.min_level, args.max_tags, args.dry_run)


if __name__ == "__main__":
    main()
