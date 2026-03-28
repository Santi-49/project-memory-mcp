# Filesystem Rules

All rules are enforced at the `MemoryFS` layer in `src/filesystem.py` — not in the MCP tool layer. This means the rules hold even if the server is used programmatically without going through the MCP interface.

---

## Path safety

Every path argument is resolved against the memory root and checked to ensure it does not escape the root directory. A `ValueError` is raised if path traversal is attempted (e.g. `../../etc/passwd`).

---

## Kebab-case filenames

New files must use kebab-case names: `[a-z0-9]+(-[a-z0-9]+)*`. The `to_kebab_case()` helper converts spaces and underscores automatically before validation. Files whose names start with `_` are exempt (covers `_meta.yaml`, `_guide.md`, `_status.md`, etc.).

**Enforced by:** `write_file`, `create_project`, `create_person`, `create_company`, `create_knowledge_entry`

---

## Append-only files

Two categories of files may only have content appended — never overwritten:

| File | Why append-only |
|---|---|
| `decisions.md` | Provides a permanent, ordered decision log |
| `updates/*.md` | Date-stamped chronological log; every entry must be preserved |

Calling `write_file` on either type raises a `ValueError` with an "append-only" message. Use `append_to_file` instead.

**Enforced by:** `is_append_only()` check in `write_file`

---

## `_index.yaml` write protection

`_index.yaml` files are never writable via `write_file` or `append_to_file`. They are only updated through:
- `add_manifest_entry` (called internally on every write)
- `update_manifest_entry` (called by `update_file_description`)
- `rebuild_manifest` (called by `update_manifest`)

Calling `read_file` on `_index.yaml` is also blocked — use `get_folder_manifest` for a rendered view.

**Enforced by:** `is_manifest()` check in both `write_file` and `append_to_file`

---

## Knowledge frontmatter

Any `.md` file written under a path that contains `knowledge/` must begin with a YAML frontmatter block delimited by `---`. The frontmatter is validated against `KnowledgeFrontmatter` (see `src/models.py`). Missing or invalid frontmatter produces a **warning** (not an error) — the file is still written.

**Enforced by:** `validate_knowledge_frontmatter()` called in `write_file`

---

## `@ref` resolution warnings

When a file references `@slug` tokens, the server checks whether `_global/people/{slug}.md` or `_global/companies/{slug}.md` exists. If neither exists, a warning is added to the response:

```
Unresolved ref: @john-doe (not found in _global/people or _global/companies)
```

This is a **warning, not an error** — the file is still written. Create the entity with `create_person` or `create_company` to silence the warning.

**Enforced by:** `warn_unresolved_refs()` called in `write_file` and `append_to_file`

---

## Unique project slugs

`create_project` checks `_projects-index.json` before creating the directory. If the slug already exists, an error is returned and no files are written.

---

## Date format

All date fields stored in YAML or JSON (`created`, `updated`, `last_updated`, `processed`, `last_entry_date`) must be `YYYY-MM-DD` format. Validated by Pydantic in `src/models.py`.

---

## Soft delete only

Files are never permanently deleted via the MCP server. `delete_file` moves the file to `_trash/{timestamp}_{filename}` and removes the manifest entry. The `_refs-index.json` entry is also removed. To permanently delete, remove the file from `_trash/` on disk directly.

---

## Manifest staleness

A folder's `_index.yaml` is marked `stale: true` when `append_to_file` is called on `decisions.md`. This signals that the manifest's file-level descriptions may be outdated relative to the file's current content. Call `update_manifest` to rebuild and clear the stale flag.

The `updates/` folder uses a different convention: instead of tracking per-file entries (which would become stale immediately after every append), its `_index.yaml` holds only a static folder description and a `last_entry_date` field. Appending to an `updates/*.md` file updates `last_entry_date` without marking the folder stale.

---

## Summary table

| Rule | Trigger | Severity |
|---|---|---|
| Path must stay inside memory root | Any path argument | Error |
| Filenames must be kebab-case | `write_file`, `create_*` | Error |
| `updates/` and `decisions.md` are append-only | `write_file` | Error |
| `_index.yaml` is not directly writable or readable | `write_file`, `append_to_file`, `read_file` | Error |
| Knowledge entries require YAML frontmatter | `write_file` on `knowledge/*.md` | Warning |
| Unresolved `@ref` tokens | `write_file`, `append_to_file` | Warning |
| Unique project slugs | `create_project` | Error |
| Date fields must be `YYYY-MM-DD` | Pydantic model validation | Error |
