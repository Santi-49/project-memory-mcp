#!/usr/bin/env python3
"""Migrate markdown files with escaped newlines to proper newline formatting.

This script scans all .md files in memory-root/ and fixes files that contain
literal \\n, \\r\\n, or \\r escape sequences (instead of actual newlines).

Usage:
    python scripts/migrate_newlines.py [--dry-run]

Options:
    --dry-run   Show what would be changed without modifying files
"""

import argparse
import sys
from pathlib import Path


def normalize_newlines(content: str) -> str:
    """Normalize escape sequence newlines to actual newlines."""
    # Replace escaped sequences with actual newlines
    content = content.replace("\\r\\n", "\n")
    content = content.replace("\\n", "\n")
    content = content.replace("\\r", "\n")
    return content


def has_escaped_newlines(content: str) -> bool:
    """Check if content has literal escape sequence newlines."""
    return "\\n" in content or "\\r" in content


def migrate_file(file_path: Path, dry_run: bool = False) -> bool:
    """Migrate a single file. Returns True if changes were made."""
    try:
        content = file_path.read_text(encoding="utf-8")

        if not has_escaped_newlines(content):
            return False

        normalized = normalize_newlines(content)

        if normalized == content:
            return False

        if not dry_run:
            file_path.write_text(normalized, encoding="utf-8")

        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Migrate escaped newlines in markdown files to proper formatting"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    args = parser.parse_args()

    # Find memory-root relative to script location
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    memory_root = repo_root / "memory-root"

    if not memory_root.exists():
        print(f"Error: memory-root not found at {memory_root}", file=sys.stderr)
        return 1

    print(f"Scanning {memory_root} for escaped newlines...")
    if args.dry_run:
        print("(DRY RUN - no files will be modified)\n")

    # Find all .md files
    md_files = list(memory_root.glob("**/*.md"))

    if not md_files:
        print("No markdown files found.")
        return 0

    migrated_count = 0
    checked_count = 0

    for file_path in sorted(md_files):
        checked_count += 1
        if migrate_file(file_path, dry_run=args.dry_run):
            migrated_count += 1
            rel_path = file_path.relative_to(memory_root)
            if args.dry_run:
                print(f"  [DRY RUN] Would fix: {rel_path}")
            else:
                print(f"  ✓ Fixed: {rel_path}")

    print(f"\nSummary:")
    print(f"  Checked: {checked_count} files")
    print(f"  Migrated: {migrated_count} files")

    if args.dry_run and migrated_count > 0:
        print(f"\nRun without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
