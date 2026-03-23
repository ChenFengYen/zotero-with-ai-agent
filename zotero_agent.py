#!/usr/bin/env python3
"""Zotero AI Agent — manage Zotero library with CRUD + join + dump operations."""

import argparse
import json
import os
import sys
from collections import Counter
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

DRY_RUN = False


def _zot():
    """Return a pyzotero Zotero instance."""
    if not API_KEY or not LIBRARY_ID:
        sys.exit("Error: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")
    return zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)


# ---------------------------------------------------------------------------
# READ operations
# ---------------------------------------------------------------------------


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
        count = node.get("meta", {}).get("numItems", 0)
        print(f"{prefix}[{data['key']}] {data['name']}  ({count} items)")
        for child in children_map.get(data["key"], []):
            _print_tree(child, indent + 1)

    for root in sorted(roots, key=lambda c: c["data"]["name"]):
        _print_tree(root)
    return cols


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


def list_tags(tag=None):
    """List all tags, or list items with a specific tag."""
    zot = _zot()
    if tag:
        items = zot.top(tag=tag)
        for item in items:
            data = item["data"]
            title = data.get("title", "(no title)")
            key = data.get("key", "")
            print(f"  [{key}] {title}")
        return items
    else:
        tags = zot.tags()
        for t in sorted(tags):
            print(f"  {t}")
        print(f"\nTotal: {len(tags)} tags")
        return tags


# ---------------------------------------------------------------------------
# CREATE operations
# ---------------------------------------------------------------------------


def create_item(item_type, title, **extra_fields):
    """Create a new item."""
    zot = _zot()
    template = zot.item_template(item_type)
    template["title"] = title
    template.update(extra_fields)
    if DRY_RUN:
        print(f"[DRY RUN] Would create {item_type}: '{title}'")
        return None
    resp = zot.create_items([template])
    print(f"Created: {json.dumps(resp, indent=2, ensure_ascii=False)}")
    return resp


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


def add_tags_to_item(item_key, tags):
    """Add tags to an item."""
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


# ---------------------------------------------------------------------------
# UPDATE operations
# ---------------------------------------------------------------------------


def update_item(key, **fields):
    """Update an existing item's fields."""
    zot = _zot()
    item = zot.item(key)
    if DRY_RUN:
        print(f"[DRY RUN] Would update item {key}: {fields}")
        return item
    for k, v in fields.items():
        item["data"][k] = v
    zot.update_item(item)
    print(f"Updated item {key}")
    return item


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


def move_collection(key, new_parent_key=None):
    """Move a collection under a new parent (or to top-level if no parent)."""
    zot = _zot()
    col = zot.collection(key)
    name = col["data"]["name"]
    dest = f"under {new_parent_key}" if new_parent_key else "to top-level"
    if DRY_RUN:
        print(f"[DRY RUN] Would move collection '{name}' [{key}] {dest}")
        return None
    col["data"]["parentCollection"] = new_parent_key if new_parent_key else False
    zot.update_collection(col)
    print(f"Moved collection '{name}' [{key}] {dest}")


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


# ---------------------------------------------------------------------------
# DELETE operations
# ---------------------------------------------------------------------------


def delete_item(key):
    """Delete an item by key."""
    zot = _zot()
    item = zot.item(key)
    if DRY_RUN:
        title = item["data"].get("title", "(no title)")
        print(f"[DRY RUN] Would delete item: '{title}' [{key}]")
        return
    zot.delete_item(item)
    print(f"Deleted item {key}")


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


def cleanup_collections():
    """Scan for problematic collections: deleted, empty leaves, duplicate names."""
    zot = _zot()
    cols = zot.collections()

    # Build children map to identify leaf collections
    children_set = set()
    for c in cols:
        parent = c["data"].get("parentCollection", False)
        if parent:
            children_set.add(parent)

    found_issues = False

    # 1. Deleted collections
    deleted = [c for c in cols if c["data"].get("deleted")]
    if deleted:
        found_issues = True
        print("=== DELETED collections (marked deleted but still on server) ===")
        for c in deleted:
            print(f"  [{c['key']}] {c['data']['name']}")
        print()

    # 2. Empty leaf collections (no children, no items)
    active_cols = [c for c in cols if not c["data"].get("deleted")]
    empty_leaves = []
    for c in active_cols:
        key = c["key"]
        count = c.get("meta", {}).get("numItems", 0)
        is_leaf = key not in children_set
        if is_leaf and count == 0:
            parent = c["data"].get("parentCollection", False)
            parent_name = ""
            if parent:
                for p in active_cols:
                    if p["key"] == parent:
                        parent_name = f" (parent: {p['data']['name']})"
            empty_leaves.append((c, parent_name))

    if empty_leaves:
        found_issues = True
        print("=== EMPTY leaf collections (no items, no sub-collections) ===")
        for c, parent_name in empty_leaves:
            print(f"  [{c['key']}] {c['data']['name']}{parent_name}")
        print()

    # 3. Duplicate collection names
    names = [c["data"]["name"] for c in active_cols]
    dupes = {n: cnt for n, cnt in Counter(names).items() if cnt > 1}
    if dupes:
        found_issues = True
        print("=== DUPLICATE collection names ===")
        for name, cnt in dupes.items():
            print(f"  '{name}' x{cnt}:")
            for c in active_cols:
                if c["data"]["name"] == name:
                    count = c.get("meta", {}).get("numItems", 0)
                    parent = c["data"].get("parentCollection", False)
                    parent_name = ""
                    if parent:
                        for p in active_cols:
                            if p["key"] == parent:
                                parent_name = f" (parent: {p['data']['name']})"
                    print(f"    [{c['key']}] {count} items{parent_name}")
        print()

    if not found_issues:
        print("No issues found. Library is clean.")

    return cols


# ---------------------------------------------------------------------------
# JOIN operation
# ---------------------------------------------------------------------------


def join_items(keys):
    """Fetch multiple items and display a comparison of their metadata."""
    zot = _zot()
    items = [zot.item(k) for k in keys]

    fields = ["title", "itemType", "date", "publicationTitle",
              "creators", "tags", "abstractNote"]

    for field in fields:
        print(f"\n{'=' * 3} {field} {'=' * 3}")
        for item in items:
            data = item["data"]
            key = data["key"]
            val = data.get(field, "")
            if field == "creators":
                val = "; ".join(
                    f"{c.get('lastName', '')}, {c.get('firstName', '')}"
                    for c in (val or [])
                ) or "(none)"
            elif field == "tags":
                val = ", ".join(t["tag"] for t in (val or [])) or "(none)"
            elif field == "abstractNote":
                val = (val[:150] + "...") if val and len(val) > 150 else (val or "(none)")
            else:
                val = val or "(none)"
            print(f"  [{key}] {val}")

    return items


# ---------------------------------------------------------------------------
# DUMP operation
# ---------------------------------------------------------------------------


def dump_items(targets, fmt="list"):
    """Export citations in various formats."""
    zot = _zot()

    # Heuristic: Zotero keys are 8 alphanumeric chars
    items = []
    is_keys = all(len(t) == 8 and t.isalnum() for t in targets)

    if is_keys:
        for key in targets:
            items.append(zot.item(key))
    else:
        # Treat as search query
        query = " ".join(targets)
        items = zot.top(q=query)

    if not items:
        print("No items found.")
        return

    if fmt == "list":
        for item in items:
            d = item["data"]
            authors = "; ".join(
                c.get("lastName", "") for c in d.get("creators", [])
            ) or "Unknown"
            year = d.get("date", "")[:4] or "n.d."
            title = d.get("title", "(no title)")
            journal = d.get("publicationTitle", "")
            line = f"- {authors} ({year}). {title}."
            if journal:
                line += f" *{journal}*."
            print(line)

    elif fmt == "bibtex":
        for item in items:
            key = item["data"]["key"]
            try:
                bib = zot.item(key, content="bibtex")
                if isinstance(bib, list):
                    print(bib[0] if bib else f"% No BibTeX for {key}")
                else:
                    print(bib)
            except Exception as e:
                print(f"% Error fetching BibTeX for {key}: {e}")
            print()

    elif fmt == "keys":
        for item in items:
            print(item["data"]["key"])

    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Zotero AI Agent — manage Zotero library"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview write operations without executing them"
    )
    sub = parser.add_subparsers(dest="operation")

    # --- read ---
    read_p = sub.add_parser("read", help="Read/query library data")
    read_sub = read_p.add_subparsers(dest="action")

    read_search = read_sub.add_parser("search", help="Search items by query")
    read_search.add_argument("query")

    read_get = read_sub.add_parser("get", help="Get item details by key")
    read_get.add_argument("key")

    read_sub.add_parser("tree", help="Show collection tree")

    read_list = read_sub.add_parser("list", help="List items in a collection")
    read_list.add_argument("collection", help="Collection key")

    read_tags = read_sub.add_parser("tags", help="List all tags, or items with a tag")
    read_tags.add_argument("tag", nargs="?", default=None, help="Optional: specific tag")

    # --- create ---
    create_p = sub.add_parser("create", help="Create items/collections/tags")
    create_sub = create_p.add_subparsers(dest="action")

    create_item_p = create_sub.add_parser("item", help="Create a new item")
    create_item_p.add_argument("item_type", help="e.g. journalArticle, book")
    create_item_p.add_argument("title")

    create_col_p = create_sub.add_parser("col", help="Create a collection")
    create_col_p.add_argument("name")
    create_col_p.add_argument("--parent", default=None, help="Parent collection key")

    create_tag_p = create_sub.add_parser("tag", help="Add tag(s) to an item")
    create_tag_p.add_argument("key", help="Item key")
    create_tag_p.add_argument("tags", nargs="+")

    # --- update ---
    update_p = sub.add_parser("update", help="Rename/move/retag")
    update_sub = update_p.add_subparsers(dest="action")

    update_rename = update_sub.add_parser("rename", help="Rename a collection or tag")
    update_rename.add_argument("type", choices=["col", "tag"])
    update_rename.add_argument("target", help="Collection key or old tag name")
    update_rename.add_argument("new_name")

    update_move = update_sub.add_parser("move", help="Move collection")
    update_move.add_argument("key", help="Collection key")
    update_move.add_argument("--parent", default=None, help="New parent key (omit for top-level)")

    update_tag = update_sub.add_parser("tag", help="Replace a tag on an item")
    update_tag.add_argument("key", help="Item key")
    update_tag.add_argument("old_tag")
    update_tag.add_argument("new_tag")

    update_item_p = update_sub.add_parser("item", help="Update item fields")
    update_item_p.add_argument("key")
    update_item_p.add_argument("fields", nargs="+", help="key=value pairs")

    # --- delete ---
    delete_p = sub.add_parser("delete", help="Delete items/collections/tags")
    delete_sub = delete_p.add_subparsers(dest="action")

    delete_item_p = delete_sub.add_parser("item", help="Delete an item")
    delete_item_p.add_argument("key")

    delete_col_p = delete_sub.add_parser("col", help="Delete a collection")
    delete_col_p.add_argument("key")

    delete_tag_p = delete_sub.add_parser("tag", help="Delete a tag globally")
    delete_tag_p.add_argument("tag")

    delete_sub.add_parser("cleanup", help="Scan for deleted/empty/duplicate collections")

    # --- join ---
    join_p = sub.add_parser("join", help="Compare multiple items side by side")
    join_p.add_argument("keys", nargs="+", help="Item keys to compare")

    # --- dump ---
    dump_p = sub.add_parser("dump", help="Export citations")
    dump_p.add_argument("targets", nargs="+", help="Search query or item keys")
    dump_p.add_argument("--fmt", choices=["list", "bibtex", "keys"], default="list")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    global DRY_RUN
    DRY_RUN = args.dry_run

    op = args.operation
    action = getattr(args, "action", None)

    if op == "read":
        if action == "search":
            search_items(args.query)
        elif action == "get":
            get_item(args.key)
        elif action == "tree":
            list_collections_tree()
        elif action == "list":
            collection_items(args.collection)
        elif action == "tags":
            list_tags(tag=args.tag)
        else:
            parser.parse_args(["read", "--help"])

    elif op == "create":
        if action == "item":
            create_item(args.item_type, args.title)
        elif action == "col":
            create_collection(args.name, parent_key=args.parent)
        elif action == "tag":
            add_tags_to_item(args.key, args.tags)
        else:
            parser.parse_args(["create", "--help"])

    elif op == "update":
        if action == "rename":
            if args.type == "col":
                rename_collection(args.target, args.new_name)
            elif args.type == "tag":
                rename_tag(args.target, args.new_name)
        elif action == "move":
            move_collection(args.key, new_parent_key=args.parent)
        elif action == "tag":
            remove_tags_from_item(args.key, [args.old_tag])
            add_tags_to_item(args.key, [args.new_tag])
        elif action == "item":
            fields = dict(f.split("=", 1) for f in args.fields)
            update_item(args.key, **fields)
        else:
            parser.parse_args(["update", "--help"])

    elif op == "delete":
        if action == "item":
            delete_item(args.key)
        elif action == "col":
            delete_collection(args.key)
        elif action == "tag":
            delete_tag(args.tag)
        elif action == "cleanup":
            cleanup_collections()
        else:
            parser.parse_args(["delete", "--help"])

    elif op == "join":
        join_items(args.keys)

    elif op == "dump":
        dump_items(args.targets, fmt=args.fmt)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
