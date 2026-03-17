#!/usr/bin/env python3
"""Zotero AI Agent — manage Zotero library and analyze PDFs with Claude CLI."""

import argparse
import json
import os
import subprocess
import sys
import textwrap
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
ZOTFILE_DIR = os.getenv("ZOTFILE_DIR", "")
TAXONOMY_FILE = Path(__file__).parent / "tag_taxonomy.json"


def _zot():
    """Return a pyzotero Zotero instance."""
    if not API_KEY or not LIBRARY_ID:
        sys.exit("Error: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")
    return zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def list_items(limit=25):
    """List recent items."""
    zot = _zot()
    items = zot.top(limit=limit)
    for item in items:
        data = item["data"]
        title = data.get("title", "(no title)")
        key = data.get("key", "")
        item_type = data.get("itemType", "")
        print(f"[{key}] ({item_type}) {title}")
    return items


def search_items(query):
    """Search items by title/creator/tag."""
    zot = _zot()
    items = zot.top(q=query)
    for item in items:
        data = item["data"]
        title = data.get("title", "(no title)")
        key = data.get("key", "")
        print(f"[{key}] {title}")
    return items


def get_item(key):
    """Get a single item by key and print its metadata."""
    zot = _zot()
    item = zot.item(key)
    print(json.dumps(item["data"], indent=2, ensure_ascii=False))
    return item


def create_item(item_type, title, **extra_fields):
    """Create a new item."""
    zot = _zot()
    template = zot.item_template(item_type)
    template["title"] = title
    template.update(extra_fields)
    resp = zot.create_items([template])
    print(f"Created: {json.dumps(resp, indent=2, ensure_ascii=False)}")
    return resp


def update_item(key, **fields):
    """Update an existing item's fields."""
    zot = _zot()
    item = zot.item(key)
    for k, v in fields.items():
        item["data"][k] = v
    zot.update_item(item)
    print(f"Updated item {key}")
    return item


def delete_item(key):
    """Delete an item by key."""
    zot = _zot()
    item = zot.item(key)
    zot.delete_item(item)
    print(f"Deleted item {key}")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

DRY_RUN = False


def list_collections():
    """List all collections (flat list with hierarchy info)."""
    zot = _zot()
    cols = zot.collections()
    # Build parent lookup for display
    name_map = {c["key"]: c["data"]["name"] for c in cols}
    for c in cols:
        data = c["data"]
        key = data["key"]
        name = data["name"]
        parent = data.get("parentCollection", False)
        count = data.get("numItems", 0)
        if parent and parent in name_map:
            print(f"  [{key}] {name}  ({count} items, parent: {name_map[parent]})")
        else:
            print(f"[{key}] {name}  ({count} items)")
    return cols


def list_collections_tree():
    """List collections as a tree structure."""
    zot = _zot()
    cols = zot.collections()
    # Build tree
    by_key = {c["key"]: c for c in cols}
    roots = []
    children_map = {}
    for c in cols:
        parent = c["data"].get("parentCollection", False)
        if parent and parent in by_key:
            children_map.setdefault(parent, []).append(c)
        else:
            roots.append(c)

    def _print_tree(node, indent=0):
        data = node["data"]
        prefix = "  " * indent + ("├─ " if indent > 0 else "")
        count = data.get("numItems", 0)
        print(f"{prefix}[{data['key']}] {data['name']}  ({count} items)")
        for child in children_map.get(data["key"], []):
            _print_tree(child, indent + 1)

    for root in sorted(roots, key=lambda c: c["data"]["name"]):
        _print_tree(root)
    return cols


def create_collection(name, parent_key=None):
    """Create a new collection, optionally under a parent."""
    if DRY_RUN:
        parent_info = f" under parent {parent_key}" if parent_key else ""
        print(f"[DRY RUN] Would create collection: '{name}'{parent_info}")
        return None
    zot = _zot()
    payload = {"name": name}
    if parent_key:
        payload["parentCollection"] = parent_key
    resp = zot.create_collections([payload])
    print(f"Created collection: '{name}'")
    if resp.get("successful"):
        for k, v in resp["successful"].items():
            print(f"  Key: {v['data']['key']}")
    return resp


def delete_collection(key):
    """Delete a collection (items are NOT deleted)."""
    zot = _zot()
    col = zot.collection(key)
    name = col["data"]["name"]
    if DRY_RUN:
        print(f"[DRY RUN] Would delete collection: '{name}' [{key}]")
        print(f"  (Items inside will NOT be deleted)")
        return None
    zot.delete_collection(col)
    print(f"Deleted collection: '{name}' [{key}] (items preserved)")


def move_collection(key, new_parent_key=None):
    """Move a collection under a new parent (or to top-level if no parent)."""
    zot = _zot()
    col = zot.collection(key)
    name = col["data"]["name"]
    if DRY_RUN:
        dest = f"under {new_parent_key}" if new_parent_key else "to top-level"
        print(f"[DRY RUN] Would move collection '{name}' [{key}] {dest}")
        return None
    col["data"]["parentCollection"] = new_parent_key if new_parent_key else False
    zot.update_collection(col)
    dest = f"under {new_parent_key}" if new_parent_key else "to top-level"
    print(f"Moved collection '{name}' [{key}] {dest}")


def rename_collection(key, new_name):
    """Rename a collection."""
    zot = _zot()
    col = zot.collection(key)
    old_name = col["data"]["name"]
    if DRY_RUN:
        print(f"[DRY RUN] Would rename collection '{old_name}' → '{new_name}'")
        return None
    col["data"]["name"] = new_name
    zot.update_collection(col)
    print(f"Renamed collection: '{old_name}' → '{new_name}'")


def collection_items(key):
    """List items in a collection."""
    zot = _zot()
    items = zot.collection_items(key)
    for item in items:
        data = item["data"]
        title = data.get("title", "(no title)")
        ikey = data.get("key", "")
        item_type = data.get("itemType", "")
        print(f"  [{ikey}] ({item_type}) {title}")
    return items


def add_to_collection(collection_key, item_key):
    """Add an item to a collection."""
    zot = _zot()
    item = zot.item(item_key)
    if DRY_RUN:
        title = item["data"].get("title", "(no title)")
        print(f"[DRY RUN] Would add '{title}' [{item_key}] to collection {collection_key}")
        return None
    zot.addto_collection(collection_key, item)
    print(f"Added item {item_key} to collection {collection_key}")


def remove_from_collection(collection_key, item_key):
    """Remove an item from a collection (item is NOT deleted)."""
    zot = _zot()
    item = zot.item(item_key)
    title = item["data"].get("title", "(no title)")
    if DRY_RUN:
        print(f"[DRY RUN] Would remove '{title}' [{item_key}] from collection {collection_key}")
        print(f"  (Item will NOT be deleted from library)")
        return None
    zot.removefrom_collection(collection_key, item)
    print(f"Removed '{title}' [{item_key}] from collection {collection_key} (item preserved)")


# ---------------------------------------------------------------------------
# Tag CRUD helpers
# ---------------------------------------------------------------------------


def list_tags():
    """List all tags in the library."""
    zot = _zot()
    tags = zot.tags()
    for t in sorted(tags):
        print(f"  {t}")
    print(f"\nTotal: {len(tags)} tags")
    return tags


def list_items_by_tag(tag):
    """List all items with a specific tag."""
    zot = _zot()
    items = zot.top(tag=tag)
    for item in items:
        data = item["data"]
        title = data.get("title", "(no title)")
        key = data.get("key", "")
        print(f"  [{key}] {title}")
    return items


def add_tags_to_item(item_key, tags):
    """Add tags to an item (respects DRY_RUN)."""
    zot = _zot()
    item = zot.item(item_key)
    existing = {t["tag"] for t in item["data"].get("tags", [])}
    new_tags = [t for t in tags if t not in existing]
    if not new_tags:
        print(f"Item {item_key} already has all specified tags.")
        return item
    if DRY_RUN:
        print(f"[DRY RUN] Would add tags {new_tags} to item {item_key}")
        return item
    item["data"]["tags"].extend({"tag": t} for t in new_tags)
    zot.update_item(item)
    print(f"Added tags {new_tags} to item {item_key}")
    return item


def remove_tags_from_item(item_key, tags):
    """Remove tags from an item."""
    zot = _zot()
    item = zot.item(item_key)
    tags_set = set(tags)
    if DRY_RUN:
        print(f"[DRY RUN] Would remove tags {tags} from item {item_key}")
        return item
    item["data"]["tags"] = [
        t for t in item["data"].get("tags", []) if t["tag"] not in tags_set
    ]
    zot.update_item(item)
    print(f"Removed tags {tags} from item {item_key}")
    return item


def rename_tag(old_tag, new_tag):
    """Rename a tag globally across all items."""
    zot = _zot()
    items = zot.top(tag=old_tag, limit=100)
    if not items:
        print(f"No items found with tag '{old_tag}'")
        return
    if DRY_RUN:
        print(f"[DRY RUN] Would rename tag '{old_tag}' → '{new_tag}' on {len(items)} items")
        return
    for item in items:
        for t in item["data"].get("tags", []):
            if t["tag"] == old_tag:
                t["tag"] = new_tag
        zot.update_item(item)
    print(f"Renamed tag '{old_tag}' → '{new_tag}' on {len(items)} items")


def delete_tag(tag):
    """Delete a tag globally from all items."""
    zot = _zot()
    items = zot.top(tag=tag, limit=100)
    if not items:
        print(f"No items found with tag '{tag}'")
        return
    if DRY_RUN:
        print(f"[DRY RUN] Would delete tag '{tag}' from {len(items)} items")
        return
    for item in items:
        item["data"]["tags"] = [
            t for t in item["data"].get("tags", []) if t["tag"] != tag
        ]
        zot.update_item(item)
    print(f"Deleted tag '{tag}' from {len(items)} items")


# ---------------------------------------------------------------------------
# Collection flattening
# ---------------------------------------------------------------------------


def _build_collection_hierarchy(cols):
    """Compute depth and ancestor chain for each collection.

    Returns dict: {key: {"data": ..., "depth": int, "ancestors": [key, ...]}}
    The ancestors list is ordered from immediate parent to root.
    """
    by_key = {c["key"]: c for c in cols}
    info = {}

    def _resolve(key, visited=None):
        if key in info:
            return info[key]
        if visited is None:
            visited = set()
        if key in visited:
            # cycle guard
            info[key] = {"data": by_key[key]["data"], "depth": 0, "ancestors": []}
            return info[key]
        visited.add(key)
        parent = by_key[key]["data"].get("parentCollection", False)
        if not parent or parent not in by_key:
            info[key] = {"data": by_key[key]["data"], "depth": 0, "ancestors": []}
        else:
            parent_info = _resolve(parent, visited)
            info[key] = {
                "data": by_key[key]["data"],
                "depth": parent_info["depth"] + 1,
                "ancestors": [parent] + parent_info["ancestors"],
            }
        return info[key]

    for key in by_key:
        _resolve(key)
    return info


def flatten_collections():
    """Flatten collections deeper than depth 1 (keep only 2 levels).

    For each collection at depth >= 2 (processing deepest first):
    1. Convert collection name to a tag with 'col:' prefix
    2. Tag all items in that collection
    3. Move items to the depth-1 ancestor collection
    4. Delete the flattened collection
    """
    zot = _zot()
    cols = zot.collections()
    hierarchy = _build_collection_hierarchy(cols)

    # Find collections at depth >= 2, sort deepest first
    to_flatten = [
        (key, h) for key, h in hierarchy.items() if h["depth"] >= 2
    ]
    to_flatten.sort(key=lambda x: -x[1]["depth"])

    if not to_flatten:
        print("No collections deeper than 2 levels. Nothing to flatten.")
        return

    print(f"Found {len(to_flatten)} collection(s) to flatten:")
    for key, h in to_flatten:
        print(f"  depth={h['depth']}  [{key}] {h['data']['name']}")

    for key, h in to_flatten:
        col_name = h["data"]["name"]
        tag_name = f"col:{col_name}"
        # depth-1 ancestor is the one at index (depth - 2) in the ancestors list
        # ancestors = [parent, grandparent, ...], depth-1 ancestor has depth=1
        depth1_ancestor = h["ancestors"][h["depth"] - 2]

        items = zot.collection_items(key)
        # Filter to top-level items only (skip attachments/notes)
        items = [i for i in items if i["data"].get("itemType") not in ("attachment", "note")]

        if DRY_RUN:
            print(f"\n[DRY RUN] Flatten '{col_name}' [{key}] (depth={h['depth']}):")
            print(f"  → Tag items with '{tag_name}'")
            print(f"  → Move {len(items)} item(s) to [{depth1_ancestor}]")
            print(f"  → Delete collection [{key}]")
            continue

        # 1-2: Tag items
        for item in items:
            existing = {t["tag"] for t in item["data"].get("tags", [])}
            if tag_name not in existing:
                item["data"]["tags"].append({"tag": tag_name})
                zot.update_item(item)

        # 3: Move items to depth-1 ancestor
        for item in items:
            zot.addto_collection(depth1_ancestor, item)

        # 4: Delete collection
        col = zot.collection(key)
        zot.delete_collection(col)
        print(f"Flattened '{col_name}' → tag '{tag_name}', items → [{depth1_ancestor}]")


# ---------------------------------------------------------------------------
# Tag Taxonomy (AI-driven)
# ---------------------------------------------------------------------------


def _load_taxonomy():
    """Load taxonomy from JSON file, or return empty structure."""
    if TAXONOMY_FILE.is_file():
        with open(TAXONOMY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "categories": {}}


def _save_taxonomy(taxonomy):
    """Save taxonomy to JSON file."""
    with open(TAXONOMY_FILE, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, indent=2, ensure_ascii=False)
    print(f"Taxonomy saved to {TAXONOMY_FILE}")


def _get_all_taxonomy_tags(taxonomy):
    """Get a flat set of all tags registered in the taxonomy."""
    tags = set()
    for cat in taxonomy.get("categories", {}).values():
        tags.update(cat.get("tags", []))
    return tags


def build_taxonomy(sample_size=50):
    """Use Claude to analyze library metadata and build a tag taxonomy."""
    zot = _zot()
    items = zot.top(limit=sample_size)

    # Collect metadata summaries
    summaries = []
    for item in items:
        data = item["data"]
        if data.get("itemType") in ("attachment", "note"):
            continue
        entry = {
            "title": data.get("title", ""),
            "tags": [t["tag"] for t in data.get("tags", [])],
            "itemType": data.get("itemType", ""),
        }
        creators = data.get("creators", [])
        if creators:
            entry["firstAuthor"] = creators[0].get("lastName", "")
        abstract = data.get("abstractNote", "")
        if abstract:
            entry["abstract"] = abstract[:200]
        summaries.append(entry)

    prompt = textwrap.dedent(f"""\
        You are a research librarian. Analyze these {len(summaries)} Zotero items
        and create a tag taxonomy for organizing an academic library.

        Items:
        {json.dumps(summaries, indent=2, ensure_ascii=False)}

        Return ONLY valid JSON (no markdown fences) with this structure:
        {{
          "version": 1,
          "categories": {{
            "domain": {{
              "description": "Research domains/fields",
              "tags": ["tag1", "tag2", ...]
            }},
            "method": {{
              "description": "Research methods or paper types",
              "tags": ["survey", "empirical", ...]
            }},
            "status": {{
              "description": "Reading status",
              "tags": ["to-read", "reading", "read", "reference"]
            }}
          }}
        }}

        Guidelines:
        - Use lowercase, hyphenated tag names (e.g. "deep-learning")
        - Keep tags specific but not too granular (aim for 5-15 per category)
        - You may add more categories beyond domain/method/status if appropriate
        - Base domain/method tags on the actual content of the items provided
    """)

    print(f"Analyzing {len(summaries)} items to build taxonomy...")
    result = subprocess.run(
        ["claude", "-p", "-"],
        input=prompt,
        capture_output=True, text=True, shell=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"Error running claude: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse JSON from Claude response
    response = result.stdout.strip()
    # Strip markdown fences if present
    if response.startswith("```"):
        lines = response.split("\n")
        response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    taxonomy = json.loads(response)
    _save_taxonomy(taxonomy)
    show_taxonomy()
    return taxonomy


def show_taxonomy():
    """Display the current tag taxonomy."""
    taxonomy = _load_taxonomy()
    if not taxonomy.get("categories"):
        print("No taxonomy found. Run 'tag taxonomy build' first.")
        return
    print(f"Tag Taxonomy (version {taxonomy.get('version', '?')}):")
    print("=" * 50)
    for cat_name, cat in sorted(taxonomy["categories"].items()):
        desc = cat.get("description", "")
        tags = cat.get("tags", [])
        print(f"\n[{cat_name}] {desc}")
        for tag in sorted(tags):
            print(f"  - {tag}")
    print()


def edit_taxonomy(category, action, tag):
    """Add or remove a tag in a taxonomy category."""
    taxonomy = _load_taxonomy()
    cats = taxonomy.setdefault("categories", {})

    if action == "add":
        if category not in cats:
            cats[category] = {"description": category, "tags": []}
        if tag in cats[category]["tags"]:
            print(f"Tag '{tag}' already in category '{category}'")
            return
        cats[category]["tags"].append(tag)
        _save_taxonomy(taxonomy)
        print(f"Added '{tag}' to category '{category}'")
    elif action == "remove":
        if category not in cats or tag not in cats[category].get("tags", []):
            print(f"Tag '{tag}' not found in category '{category}'")
            return
        cats[category]["tags"].remove(tag)
        _save_taxonomy(taxonomy)
        print(f"Removed '{tag}' from category '{category}'")
    else:
        print(f"Unknown action '{action}'. Use 'add' or 'remove'.")


# ---------------------------------------------------------------------------
# AI Auto-tagging
# ---------------------------------------------------------------------------


def auto_tag_item(item_key, auto_confirm=False):
    """Use Claude to suggest tags for an item from the taxonomy."""
    taxonomy = _load_taxonomy()
    if not taxonomy.get("categories"):
        sys.exit("Error: No taxonomy found. Run 'tag taxonomy build' first.")

    zot = _zot()
    item = zot.item(item_key)
    data = item["data"]

    # Build item context
    item_info = {
        "title": data.get("title", ""),
        "itemType": data.get("itemType", ""),
        "abstract": data.get("abstractNote", ""),
        "tags": [t["tag"] for t in data.get("tags", [])],
        "creators": [
            f"{c.get('firstName', '')} {c.get('lastName', '')}"
            for c in data.get("creators", [])
        ],
    }

    # Try to get PDF content
    pdf_path = find_pdf_by_key(item_key)
    pdf_hint = ""
    if pdf_path:
        pdf_hint = f"\nThe PDF is available at: {pdf_path.as_posix()}"

    prompt = textwrap.dedent(f"""\
        You are a research librarian. Suggest tags for this academic item
        from the following taxonomy ONLY. Do NOT invent new tags.

        TAXONOMY:
        {json.dumps(taxonomy["categories"], indent=2, ensure_ascii=False)}

        ITEM:
        {json.dumps(item_info, indent=2, ensure_ascii=False)}
        {pdf_hint}

        Return ONLY valid JSON (no markdown fences): a list of tag strings.
        Example: ["deep-learning", "survey", "to-read"]
        Choose the most relevant tags from each applicable category.
    """)

    cmd = ["claude", "-p", "-"]
    if pdf_path:
        cmd.append(pdf_path.as_posix())

    print(f"Analyzing: {item_info['title']}")
    result = subprocess.run(
        cmd, input=prompt,
        capture_output=True, text=True, shell=True, encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"Error running claude: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    response = result.stdout.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        response = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    suggested_tags = json.loads(response)
    allowed_tags = _get_all_taxonomy_tags(taxonomy)
    suggested_tags = [t for t in suggested_tags if t in allowed_tags]

    existing = {t["tag"] for t in data.get("tags", [])}
    new_tags = [t for t in suggested_tags if t not in existing]

    if not new_tags:
        print("No new tags to add.")
        return

    print(f"Suggested tags: {new_tags}")

    if not auto_confirm:
        answer = input("Apply these tags? [y/N] ").strip().lower()
        if answer != "y":
            print("Skipped.")
            return

    add_tags_to_item(item_key, new_tags)


def auto_tag_batch(collection_key, auto_confirm=False):
    """Auto-tag all items in a collection."""
    zot = _zot()
    items = zot.collection_items(collection_key)
    items = [i for i in items if i["data"].get("itemType") not in ("attachment", "note")]

    print(f"Auto-tagging {len(items)} items in collection {collection_key}...")
    for item in items:
        key = item["data"]["key"]
        title = item["data"].get("title", "(no title)")
        print(f"\n--- [{key}] {title} ---")
        try:
            auto_tag_item(key, auto_confirm=auto_confirm)
        except Exception as e:
            print(f"  Error: {e}")


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------


def find_pdf(citekey):
    """Find a PDF in ZOTFILE_DIR matching the citekey."""
    if not ZOTFILE_DIR:
        sys.exit("Error: ZOTFILE_DIR must be set in .env")
    base = Path(ZOTFILE_DIR)
    if not base.is_dir():
        sys.exit(f"Error: ZOTFILE_DIR does not exist: {ZOTFILE_DIR}")

    # Try exact match first, then glob
    exact = base / f"{citekey}.pdf"
    if exact.is_file():
        print(str(exact))
        return exact

    matches = list(base.glob(f"*{citekey}*.pdf"))
    if matches:
        for m in matches:
            print(str(m))
        return matches[0]

    print(f"No PDF found for citekey: {citekey}")
    return None


def find_pdf_by_key(key):
    """Find a PDF attachment for a Zotero item key and return its local path."""
    zot = _zot()
    children = zot.children(key)
    for child in children:
        data = child["data"]
        if data.get("contentType") == "application/pdf":
            # Check if we have a local file path via ZOTFILE_DIR
            filename = data.get("filename", "")
            if filename and ZOTFILE_DIR:
                local_path = Path(ZOTFILE_DIR) / filename
                if local_path.is_file():
                    return local_path
            # Try title-based lookup
            title = data.get("title", "")
            if title and ZOTFILE_DIR:
                local_path = Path(ZOTFILE_DIR) / title
                if local_path.is_file():
                    return local_path
    return None


# ---------------------------------------------------------------------------
# Claude CLI integration
# ---------------------------------------------------------------------------


def analyze_pdf(key, prompt=None, first_page_only=False):
    """Analyze a PDF with Claude CLI.

    Finds the PDF for the given Zotero item key, then calls
    `claude -p` with the PDF content piped in.
    """
    pdf_path = find_pdf_by_key(key)
    if not pdf_path:
        sys.exit(f"Error: no local PDF found for item {key}")

    if prompt is None:
        prompt = "Please summarize this academic paper, including its main contributions, methodology, and key findings."

    # Build claude command
    cmd = ["claude", "-p", prompt]
    if first_page_only:
        # Read only first page — we pass a hint in the prompt instead
        prompt += "\n\n(Focus only on the first page of the document.)"
        cmd = ["claude", "-p", prompt]

    # Pass PDF path as an argument to claude
    # Claude CLI accepts file paths after the prompt
    cmd.extend([pdf_path.as_posix()])

    print(f"Analyzing: {pdf_path}")
    print(f"Prompt: {prompt}")
    print("-" * 60)

    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Error running claude: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(result.stdout)
    return result.stdout


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Zotero AI Agent — manage library & analyze PDFs"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview write operations without executing them"
    )
    sub = parser.add_subparsers(dest="command")

    # --- collections ---
    col_p = sub.add_parser("col", help="Collection operations")
    col_sub = col_p.add_subparsers(dest="action")

    col_sub.add_parser("list", help="List all collections (flat)")
    col_sub.add_parser("tree", help="List collections as tree")

    col_items_p = col_sub.add_parser("items", help="List items in a collection")
    col_items_p.add_argument("key", help="Collection key")

    col_create_p = col_sub.add_parser("create", help="Create a collection")
    col_create_p.add_argument("name")
    col_create_p.add_argument("--parent", default=None, help="Parent collection key")

    col_delete_p = col_sub.add_parser("delete", help="Delete a collection (keeps items)")
    col_delete_p.add_argument("key")

    col_rename_p = col_sub.add_parser("rename", help="Rename a collection")
    col_rename_p.add_argument("key")
    col_rename_p.add_argument("new_name")

    col_move_p = col_sub.add_parser("move", help="Move collection under a new parent")
    col_move_p.add_argument("key")
    col_move_p.add_argument("--parent", default=None, help="New parent key (omit for top-level)")

    col_add_p = col_sub.add_parser("add-item", help="Add an item to a collection")
    col_add_p.add_argument("key", help="Collection key")
    col_add_p.add_argument("item_key", help="Item key")

    col_rm_p = col_sub.add_parser("rm-item", help="Remove item from collection (keeps item)")
    col_rm_p.add_argument("key", help="Collection key")
    col_rm_p.add_argument("item_key", help="Item key")

    col_sub.add_parser("flatten", help="Flatten collections deeper than 2 levels")

    # --- tags ---
    tag_p = sub.add_parser("tag", help="Tag operations")
    tag_sub = tag_p.add_subparsers(dest="action")

    tag_sub.add_parser("list", help="List all tags")

    tag_li_p = tag_sub.add_parser("list-items", help="List items with a specific tag")
    tag_li_p.add_argument("tag", help="Tag name")

    tag_add_p = tag_sub.add_parser("add", help="Add tags to an item")
    tag_add_p.add_argument("item_key", help="Item key")
    tag_add_p.add_argument("tags", nargs="+", help="Tags to add")

    tag_rm_p = tag_sub.add_parser("remove", help="Remove tags from an item")
    tag_rm_p.add_argument("item_key", help="Item key")
    tag_rm_p.add_argument("tags", nargs="+", help="Tags to remove")

    tag_rename_p = tag_sub.add_parser("rename", help="Rename a tag globally")
    tag_rename_p.add_argument("old", help="Old tag name")
    tag_rename_p.add_argument("new", help="New tag name")

    tag_del_p = tag_sub.add_parser("delete", help="Delete a tag globally")
    tag_del_p.add_argument("tag", help="Tag to delete")

    # taxonomy sub-sub-commands
    tax_p = tag_sub.add_parser("taxonomy", help="Tag taxonomy operations")
    tax_sub = tax_p.add_subparsers(dest="tax_action")

    tax_build_p = tax_sub.add_parser("build", help="AI-build tag taxonomy")
    tax_build_p.add_argument("-n", "--sample-size", type=int, default=50)

    tax_sub.add_parser("show", help="Show current taxonomy")

    tax_edit_p = tax_sub.add_parser("edit", help="Edit taxonomy")
    tax_edit_p.add_argument("edit_action", choices=["add", "remove"])
    tax_edit_p.add_argument("category")
    tax_edit_p.add_argument("tag")

    # auto-tag commands
    tag_auto_p = tag_sub.add_parser("auto", help="AI auto-tag a single item")
    tag_auto_p.add_argument("item_key", help="Item key")
    tag_auto_p.add_argument("--yes", action="store_true", help="Skip confirmation")

    tag_batch_p = tag_sub.add_parser("auto-batch", help="AI auto-tag all items in a collection")
    tag_batch_p.add_argument("collection_key", help="Collection key")
    tag_batch_p.add_argument("--yes", action="store_true", help="Skip confirmation")

    # --- items ---
    items_p = sub.add_parser("items", help="CRUD operations on items")
    items_sub = items_p.add_subparsers(dest="action")

    list_p = items_sub.add_parser("list", help="List recent items")
    list_p.add_argument("-n", "--limit", type=int, default=25)

    search_p = items_sub.add_parser("search", help="Search items")
    search_p.add_argument("query")

    get_p = items_sub.add_parser("get", help="Get item by key")
    get_p.add_argument("key")

    create_p = items_sub.add_parser("create", help="Create a new item")
    create_p.add_argument("item_type", help="e.g. journalArticle, book")
    create_p.add_argument("title")

    update_p = items_sub.add_parser("update", help="Update an item")
    update_p.add_argument("key")
    update_p.add_argument(
        "fields", nargs="+", help="key=value pairs, e.g. title='New Title'"
    )

    delete_p = items_sub.add_parser("delete", help="Delete an item")
    delete_p.add_argument("key")

    # --- pdf ---
    pdf_p = sub.add_parser("pdf", help="PDF operations")
    pdf_sub = pdf_p.add_subparsers(dest="action")

    find_p = pdf_sub.add_parser("find", help="Find PDF by citekey")
    find_p.add_argument("citekey")

    # --- analyze ---
    analyze_p = sub.add_parser("analyze", help="Analyze PDF with Claude")
    analyze_p.add_argument("key", help="Zotero item key")
    analyze_p.add_argument("-p", "--prompt", default=None)
    analyze_p.add_argument(
        "--first-page", action="store_true", help="Focus on first page only"
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    global DRY_RUN
    DRY_RUN = args.dry_run

    if args.command == "col":
        if args.action == "list":
            list_collections()
        elif args.action == "tree":
            list_collections_tree()
        elif args.action == "items":
            collection_items(args.key)
        elif args.action == "create":
            create_collection(args.name, parent_key=args.parent)
        elif args.action == "delete":
            delete_collection(args.key)
        elif args.action == "rename":
            rename_collection(args.key, args.new_name)
        elif args.action == "move":
            move_collection(args.key, new_parent_key=args.parent)
        elif args.action == "add-item":
            add_to_collection(args.key, args.item_key)
        elif args.action == "rm-item":
            remove_from_collection(args.key, args.item_key)
        elif args.action == "flatten":
            flatten_collections()
        else:
            parser.parse_args(["col", "--help"])

    elif args.command == "tag":
        if args.action == "list":
            list_tags()
        elif args.action == "list-items":
            list_items_by_tag(args.tag)
        elif args.action == "add":
            add_tags_to_item(args.item_key, args.tags)
        elif args.action == "remove":
            remove_tags_from_item(args.item_key, args.tags)
        elif args.action == "rename":
            rename_tag(args.old, args.new)
        elif args.action == "delete":
            delete_tag(args.tag)
        elif args.action == "taxonomy":
            if args.tax_action == "build":
                build_taxonomy(sample_size=args.sample_size)
            elif args.tax_action == "show":
                show_taxonomy()
            elif args.tax_action == "edit":
                edit_taxonomy(args.category, args.edit_action, args.tag)
            else:
                parser.parse_args(["tag", "taxonomy", "--help"])
        elif args.action == "auto":
            auto_tag_item(args.item_key, auto_confirm=args.yes)
        elif args.action == "auto-batch":
            auto_tag_batch(args.collection_key, auto_confirm=args.yes)
        else:
            parser.parse_args(["tag", "--help"])

    elif args.command == "items":
        if args.action == "list":
            list_items(limit=args.limit)
        elif args.action == "search":
            search_items(args.query)
        elif args.action == "get":
            get_item(args.key)
        elif args.action == "create":
            create_item(args.item_type, args.title)
        elif args.action == "update":
            fields = {}
            for f in args.fields:
                k, v = f.split("=", 1)
                fields[k] = v
            update_item(args.key, **fields)
        elif args.action == "delete":
            delete_item(args.key)
        else:
            parser.parse_args(["items", "--help"])

    elif args.command == "pdf":
        if args.action == "find":
            find_pdf(args.citekey)
        else:
            parser.parse_args(["pdf", "--help"])

    elif args.command == "analyze":
        analyze_pdf(args.key, prompt=args.prompt, first_page_only=args.first_page)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
