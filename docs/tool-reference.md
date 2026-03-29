# Tool Reference

Complete parameter and behaviour reference for all MCP tools exposed by the Project Memory server.

---

## Response envelope

Every tool returns the same JSON envelope:

```json
{ "result": <any>, "warnings": ["..."] }
```

On failure:

```json
{ "error": "human-readable message", "warnings": [] }
```

No unhandled exceptions are ever raised — all errors are caught and returned in the envelope.

---

## Filesystem tools

### `list_projects`

List all projects registered in `_projects-index.json`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | Filter by status value (`active`, `paused`, `completed`, `archived`) |
| `type` | string | no | Filter by type value (`client`, `internal`, `research`, `personal`) |
| `tags` | string | no | Comma-separated list of tags; returns projects that match **any** tag |

Returns an array of project index entries (slug, name, status, type, path, tags, created, updated).

---

### `get_project_context`

Load the essential context for a project in a single call.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Project slug (kebab-case) |
| `deep` | boolean | no | Default `false`. When `true`, additionally returns `knowledge/_index.yaml` manifest and auto-managed `people.md` content |

**Shallow result (default):**
```json
{
  "status": "<_status.md content>",
  "meta": "<_meta.yaml content>",
  "manifest": "<rendered _index.yaml>"
}
```

**Deep result (`deep=true`):**
```json
{
  "status": "...",
  "meta": "...",
  "manifest": "...",
  "knowledge_manifest": "<rendered knowledge/_index.yaml>",
  "people": "<people.md content>"
}
```

Use `deep=true` when you need to understand stakeholders and existing knowledge before creating or editing content.

---

### `get_folder_manifest`

Render a folder's `_index.yaml` as formatted, human-readable text.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `folder_path` | string | yes | Path relative to memory root (e.g. `projects/my-api/knowledge`) |

---

### `read_file`

Read any UTF-8 file. Direct reads of `_index.yaml` are blocked — use `get_folder_manifest` instead.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path relative to memory root |

---

### `write_file`

Write a file with all rules enforced:
- Filename must be kebab-case (underscores and spaces are converted automatically during validation).
- `_index.yaml` cannot be written directly.
- `updates/*.md` and `decisions.md` are append-only (use `append_to_file`).
- `projects/{slug}/people.md` is auto-managed and cannot be written directly.
- Knowledge entries in `knowledge/` must have valid YAML frontmatter.
- `_meta.yaml`, `_guide.md`, `_status.md` are allowed (prefix `_` bypasses kebab enforcement).
- `@refs` that cannot be resolved in `_global/` produce warnings (not errors).

For existing files, read current content first to avoid unintended overwrite.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path relative to memory root |
| `content` | string | yes | File content (UTF-8) |
| `description` | string | no | Manifest entry description for this file |
| `read_when` | string | no | Manifest entry read-when hint |

Automatically updates `_index.yaml` for the containing folder and `_refs-index.json`.

---

### `append_to_file`

Append content to an append-only file. Only allowed for:
- `updates/*.md` — any Markdown file directly inside a project's `updates/` folder.
- `decisions.md` — the top-level decisions log in a project.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path relative to memory root |
| `content` | string | yes | Content to append (inserted at end of file) |

Appending to `updates/` sets `last_entry_date` on the folder manifest (does **not** mark it stale).  
Appending to `decisions.md` marks the project manifest stale.

Read the target file first when appending context-sensitive updates.

---

### `create_project`

Scaffold a complete project directory tree.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Kebab-case project identifier (must be unique) |
| `name` | string | yes | Human-readable project name |
| `status` | string | no | `active` (default), `paused`, `completed`, `archived` |
| `type` | string | no | `internal` (default), `client`, `research`, `personal` |
| `meta` | object | no | Extra metadata: `company`, `owner`, `team`, `tags` |
| `description` | string | no | One-line description written to `_meta.yaml` manifest entry |

Created layout:
```
projects/{slug}/
├── _status.md          ← always-current project status (human-editable)
├── _guide.md           ← folder structure reference (human-editable)
├── _index.yaml         ← auto-managed manifest
├── _meta.yaml          ← project metadata
├── people.md           ← auto-managed people linked from global profiles
├── companies.md
├── decisions.md
├── knowledge/
├── correspondence/
│   ├── email-threads.md
│   ├── calls.md
│   └── messages.md
├── updates/
├── docs/
└── notes/
```

---

### `create_knowledge_entry`

Create a Markdown knowledge file with validated YAML frontmatter in `projects/{slug}/knowledge/`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_slug` | string | yes | Target project slug |
| `topic` | string | yes | Topic name (converted to kebab-case for filename) |
| `content` | string | yes | Body content (Markdown) |
| `frontmatter` | object | yes | YAML frontmatter fields (see Knowledge Frontmatter below) |
| `description` | string | no | Manifest entry description |
| `read_when` | string | no | Manifest entry read-when hint |

**Knowledge frontmatter fields:**

| Field | Type | Description |
|---|---|---|
| `source` | string/null | Original source identifier (URL, meeting ID, document slug) |
| `processed` | YYYY-MM-DD/null | Date this entry was processed |
| `method` | string/null | How the entry was created (`manual`, `summary`, `extract`) |
| `model` | string/null | AI model used if applicable |
| `prompt_ref` | string/null | Reference to the prompt used |

---

### `update_manifest`

Rebuild `_index.yaml` for a folder by scanning disk contents.

- Adds placeholder entries for files not yet in the manifest.
- Removes entries for files that have been deleted from disk.
- For `updates/` folders, preserves the static folder description and skips per-file tracking.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `folder_path` | string | yes | Path relative to memory root |

---

### `update_file_description`

Targeted update of a single manifest entry's metadata. Creates the entry if it doesn't exist.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `folder_path` | string | yes | Path of the containing folder |
| `filename` | string | yes | Filename to update (e.g. `roadmap.md`) |
| `description` | string | yes | New description text |
| `read_when` | string | no | Updated read-when hint |
| `stale_after` | string | no | Updated stale-after condition |

---

### `resolve_ref`

Resolve an `@slug` reference to a global entity (person or company).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Slug to resolve (without the `@` prefix) |

Checks `_global/people/{slug}.md` first, then `_global/companies/{slug}.md`. Returns path and file content on success.

---

### `get_refs_for`

Return all files that mention a given `@ref`, `#tag`, or `[[link]]`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `ref` | string | yes | Token to search for (without `@` / `#` / `[[]]` delimiters) |

Reads from `_refs-index.json` — O(1) lookup per token.

---

### `search_files`

Full-text keyword search across `.md` files. Case-insensitive.

**Skipped paths:**
- Files whose name starts with `_` (manifests, meta, guide, status files)
- Any file under `_trash/` — soft-deleted files are intentionally excluded from search

| Parameter | Type | Required | Description |
|---|---|---|---|
| `keyword` | string | yes | Search term |
| `project_slug` | string | no | Scope search to `projects/{slug}/` — preferred for project-scoped queries |
| `folder` | string | no | Scope search to any arbitrary sub-path (power-user escape hatch) |

Returns an array of `{path, line_no, line}` objects.

---

### `delete_file`

Soft-delete a file by moving it to `_trash/{timestamp}_{filename}`. Removes the manifest entry. Does **not** remove cross-references from `_refs-index.json` (use `rebuild_refs_index` if needed).

`projects/{slug}/people.md` is auto-managed and cannot be deleted.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path relative to memory root |

---

### `list_stale_manifests`

Return the relative paths of all folders where `_index.yaml` has `stale: true`.

No parameters. A manifest is marked stale when `append_to_file` is called on `decisions.md` (the manifest can no longer accurately reflect file line ranges after an append).

---

### `rebuild_refs_index`

Rebuild `_refs-index.json` from scratch by scanning all `.md` files.

No parameters. Use this when the refs index has drifted out of sync — for example, after directly editing files on disk outside the MCP server, or after a bulk import.

---

## Global entity tools

### `create_person`

Create a global person profile in `_global/people/{slug}.md` and update the people manifest.

Before creating, call `list_global_people` first (and optionally `list_global_companies` / `resolve_ref`) to avoid duplicate entities.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Kebab-case identifier (must be unique within people) |
| `name` | string | yes | Full name |
| `title` | string | no | Job title |
| `company` | string | no | Associated company (defaults to `Other`) |
| `email` | string | no | Email address |
| `phone` | string | no | Phone number |
| `global_description` | string | no | Editable global description field inside the person profile |
| `project_slug` | string | no | Existing project slug; if provided, links person to that project after creation |
| `description` | string | no | One-line description written to manifest entry |

The person file keeps a canonical `## Projects` section that is managed by relationship tools.
It also includes a manually editable `## Notes` section managed through `edit_person_notes`.

---

### `update_person`

Update a global person profile in `_global/people/{slug}.md` and refresh linked project `people.md` files.

Read first with `get_person` to avoid overriding manual notes context.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Person slug |
| `name` | string | no | Full name |
| `title` | string | no | Job title |
| `company` | string | no | Associated company (empty value becomes `Other`) |
| `email` | string | no | Email address |
| `phone` | string | no | Phone number |
| `global_description` | string | no | Editable global description field inside the person profile |
| `description` | string | no | Manifest entry description |

---

### `link_person_to_project`

Create a person-project relationship and synchronize both sides:
- adds `[[project-slug]]` to the global person `## Projects` section
- regenerates `projects/{slug}/people.md` grouped by company

| Parameter | Type | Required | Description |
|---|---|---|---|
| `person_slug` | string | yes | Existing global person slug |
| `project_slug` | string | yes | Existing project slug |

---

### `unlink_person_from_project`

Remove a person-project relationship and synchronize both sides.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `person_slug` | string | yes | Existing global person slug |
| `project_slug` | string | yes | Existing project slug |

---

### `edit_person_notes`

Edit the manual `## Notes` section in `_global/people/{slug}.md`.

Use this tool only when the user explicitly asks to add or modify manual notes.
Call `get_person` first to preserve and reason about existing notes before changing them.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Existing global person slug |
| `notes` | string | yes | Notes text to apply |
| `mode` | string | no | `append` (default) or `replace` |

The tool updates the person file and refreshes refs indexing for note content.

---

### `create_company`

Create a company profile in `_global/companies/{slug}.md` and update the companies manifest.

Before creating, call `list_global_companies` first (and optionally `list_global_people` / `resolve_ref`) to avoid duplicate entities.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Kebab-case identifier (must be unique within companies) |
| `name` | string | yes | Company name |
| `industry` | string | no | Industry sector |
| `website` | string | no | Website URL |
| `description` | string | no | One-line description written to manifest entry |

---

### `get_person`

Read `_global/people/{slug}.md`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Person slug |

---

### `get_company`

Read `_global/companies/{slug}.md`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `slug` | string | yes | Company slug |

---

### `list_global_people`

List all entries in the `_global/people/_index.yaml` manifest.

No parameters. Returns an array of manifest entries (name, description, read_when, stale_after).

---

### `list_global_companies`

List all entries in the `_global/companies/_index.yaml` manifest.

No parameters. Returns an array of manifest entries (name, description, read_when, stale_after).

---

## Resources

MCP resources are read-only endpoints that the LLM can fetch by URI. The server exposes one resource.

| Resource URI | Description |
|---|---|
| `memory://guide` | Compact structural reference — read once per session before using any tool |

### `memory://guide`

Returns a single UTF-8 Markdown string (~800 tokens) covering:
- Root structure (dynamic — reflects the live filesystem at call time)
- Project folder layout
- Tool inventory with parameter signatures (dynamic — reflects registered tools at call time)
- Reference syntax (`@ref`, `#tag`, `[[link]]`)
- Key schemas (`_meta.yaml`, knowledge frontmatter, `_index.yaml` entry, `_status.md` frontmatter)
- Filesystem rules table (enforcement triggers and severity)

The server description instructs the LLM to read this resource before using any tool. It is not a workflow guide — navigation patterns and token-budget rules belong in the system prompt.
