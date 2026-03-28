# Memory Root Schema

This document describes every file and folder that the Project Memory MCP server creates and manages.

---

## Root layout

```
memory-root/
├── _index.yaml                  # Root manifest — lists all projects (auto-managed)
├── _projects-index.json         # Fast project lookup index (auto-managed)
├── _refs-index.json             # @ref / #tag / [[link]] cross-reference index (auto-managed)
├── _global/
│   ├── _index.yaml
│   ├── people/
│   │   ├── _index.yaml
│   │   └── {slug}.md            # One file per person
│   └── companies/
│       ├── _index.yaml
│       └── {slug}.md            # One file per company
├── _templates/                  # Reference template files (written once at init)
├── _trash/                      # Soft-deleted files land here
└── projects/
    └── {project-slug}/          # One directory per project (see Project layout below)
```

---

## Project layout

```
projects/{slug}/
├── _status.md          ← Always-current human-written status (first loaded in context)
├── _guide.md           ← Static folder structure table (human-editable)
├── _index.yaml         ← Auto-managed manifest for this directory
├── _meta.yaml          ← Project metadata (auto-populated, human-editable after creation)
├── people.md           ← Key contacts and stakeholders
├── companies.md        ← Company relationships relevant to this project
├── decisions.md        ← Architecture/key decision log (append-only)
├── knowledge/
│   ├── _index.yaml
│   └── {topic}.md      ← Processed knowledge entries (require YAML frontmatter)
├── correspondence/
│   ├── _index.yaml
│   ├── email-threads.md
│   ├── calls.md
│   └── messages.md
├── updates/
│   ├── _index.yaml     ← Special: contains folder-level description + last_entry_date only
│   └── {date}.md       ← Date-stamped update entries (append-only)
├── docs/
│   ├── _index.yaml
│   └── *.md / *.pdf    ← Reference documents and specs
└── notes/
    ├── _index.yaml
    └── *.md            ← Free-form notes
```

---

## File schemas

### `_index.yaml` (folder manifest)

```yaml
# Auto-managed by the MCP server. Edit descriptions via update_file_description tool.
last_updated: "2025-01-15"    # YYYY-MM-DD, updated on every manifest write
stale: false                  # true after append_to_file on decisions.md
description: null             # folder-level description (used by updates/ folder)
last_entry_date: null         # date of last append (used by updates/ folder only)
files:
  - name: "roadmap.md"
    description: "Product roadmap and milestone timeline."
    read_when: "Planning next sprint or reviewing timeline commitments."
    stale_after: "After any major scope change."
  - name: "api-spec.md"
    description: "API contract summary from v2 spec document."
    read_when: "Before writing any integration code."
    stale_after: null
```

The `updates/` folder manifest uses a simplified form:
```yaml
last_updated: "2025-01-15"
stale: false
description: "Chronological update log. Read the file directly for recent entries."
last_entry_date: "2025-03-28"   # date of the most recent append
files: []                        # per-file entries are not tracked for this folder
```

### `_meta.yaml` (project metadata)

```yaml
# Project metadata — auto-populated by create_project, human-editable thereafter.
id: "550e8400-e29b-41d4-a716-446655440000"   # UUID, never changes
slug: "my-api"
name: "My API Project"
status: "active"          # active | paused | completed | archived
type: "client"            # client | internal | research | personal
company: null             # @company-slug
owner: null               # @person-slug
team: []                  # list of @person-slugs
tags: []
created: "2025-01-15"     # YYYY-MM-DD, never changes
updated: "2025-03-28"     # YYYY-MM-DD, updated on human edits
```

### `_status.md` (current project status)

Human-editable. Scaffolded with a plain Markdown template (no YAML frontmatter):

```markdown
# Status — {Project Name}

> As of {date}: _(no status set yet — update this after every key event)_

**Current state:**
**Next action:**
**Blocked on:**
**Last updated:** {date}
```

The `**Last updated:** {date}` line is human-readable but not machine-parseable. If you want machine-parseable freshness metadata (recommended for RAG pipelines), prepend an optional YAML frontmatter block:

```markdown
---
last_updated: "2025-03-28"
---
# Status — {Project Name}
...
```

Either form is valid. The server does not parse `_status.md` — it reads and returns the raw content. Update this file after every significant event; it is the first field returned by `get_project_context`.

### `_guide.md` (folder structure reference)

Human-editable. Scaffolded from `_templates/project-guide.md`. This is the complete table every project receives:

```markdown
# Project Folder Guide

This folder contains structured memory for this project. Below is a quick reference
for what each file and sub-folder contains and when to read it.

| Folder / File | Contains | Read when |
|---|---|---|
| `_status.md` | Always-current project status, next action, blockers | First — before loading any other context for this project |
| `_meta.yaml` | Project metadata (status, type, owner, tags) | When filtering or understanding project scope |
| `_index.yaml` | Auto-managed manifest of all files (descriptions + read-when) | Use `get_folder_manifest` tool |
| `people.md` | Key contacts and stakeholders on this project | Before any communication or meeting |
| `companies.md` | Company relationships relevant to this project | When researching company context |
| `decisions.md` | Architecture and key decisions log (append-only) | Before making decisions that may overlap |
| `knowledge/` | Processed knowledge entries (source material, summaries) | When researching a topic |
| `correspondence/` | Email threads, calls, messages | When reviewing communication history |
| `updates/` | Chronological date-stamped update log (append-only) | For recent progress and status |
| `docs/` | Reference documents and specs | When working with external documents |
| `notes/` | Free-form notes | For general reference |

> **Note:** Never edit `_index.yaml` directly. Use the `update_file_description` tool.
> `_status.md` and `_guide.md` are human-editable and not auto-managed.
```

### `_projects-index.json`

```json
{
  "projects": [
    {
      "slug": "my-api",
      "name": "My API Project",
      "status": "active",
      "type": "client",
      "path": "projects/my-api",
      "tags": ["integration"],
      "created": "2025-01-15",
      "updated": "2025-03-28"
    }
  ]
}
```

### `_refs-index.json`

```json
{
  "entries": {
    "projects/my-api/people.md": {
      "path": "projects/my-api/people.md",
      "refs": ["john-doe", "acme-corp"],
      "tags": ["integration"],
      "links": ["API Design"]
    }
  }
}
```

Keys are paths relative to the memory root. The three arrays capture distinct token types found in the file body:

- **`refs`** — `@slug` mentions (e.g. `@john-doe` → `"john-doe"`)
- **`tags`** — `#tag` mentions (e.g. `#integration` → `"integration"`)
- **`links`** — `[[link]]` mentions (e.g. `[[API Design]]` → `"API Design"`)

Updated on every `write_file` and `append_to_file` call. Use `rebuild_refs_index` to reconstruct from scratch.

### Knowledge entry frontmatter

Every file under `knowledge/` must start with a YAML frontmatter block:

```yaml
---
source: "meeting-2025-01-15"     # original source; null if unknown
processed: "2025-01-16"          # YYYY-MM-DD; null if not yet processed
method: "manual"                  # manual | summary | extract
model: null                       # AI model used if applicable
prompt_ref: null                  # reference to the prompt used
---
```

---

## Naming conventions

| Item | Convention | Enforced by |
|---|---|---|
| Project slugs | kebab-case, alphanumeric + hyphens only | `create_project` |
| Filenames | kebab-case | `write_file`, `create_*` tools |
| Internal files | Prefixed with `_` (e.g. `_meta.yaml`) | Convention only |
| Date fields | `YYYY-MM-DD` | Pydantic validators in `models.py` |

Files prefixed with `_` are exempt from kebab-case enforcement so that internal server files like `_index.yaml` and `_meta.yaml` can be written freely.

---

## Auto-managed vs human-editable

| File | Managed by | Human-editable? |
|---|---|---|
| `_index.yaml` | MCP server only | No — use `update_file_description` |
| `_projects-index.json` | MCP server only | No — use `create_project` |
| `_refs-index.json` | MCP server only | No — use `rebuild_refs_index` |
| `_meta.yaml` | Scaffolded by server | Yes — edit freely after creation |
| `_status.md` | Scaffolded by server | Yes — update after every key event |
| `_guide.md` | Scaffolded by server | Yes — static reference |
| `people.md`, `companies.md` | Written by tools | Yes |
| `decisions.md` | Append-only via tool | Yes (append only) |
| `updates/*.md` | Append-only via tool | Yes (append only) |
| `knowledge/*.md` | Written by tools | Yes |
