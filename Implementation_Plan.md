# Project Memory MCP Server — Implementation Plan (v2)

A FastMCP-based server managing a structured project memory filesystem. Markdown + YAML files, plain filesystem, no database. Designed to support a future RAG layer without schema changes.

---

## Key Design Decisions (from user feedback)

- **`requirements.txt` only** — no pyproject.toml
- **Manifests stored as `_index.yaml`**, not `_index.md`
  - YAML is human-readable and easy to hand-edit on disk
  - Never exposed to direct `write_file` via MCP — only updated through structured tools
  - `get_folder_manifest` reads the YAML and renders it as formatted text for LLM consumption
  - Project-level folder guide lives in a static `_guide.md` (infrequently changes, human-editable)
- **Manifest entries are set on creation** via optional `description` / `read_when` / `stale_after` parameters on every creation tool
- **`update_file_description` tool** allows targeted post-creation updates to a single YAML entry

> **RAG note:** `_index.yaml` files become the primary metadata pre-filter for query routing (the "Read when" field). YAML is a first-class embedding target without needing markdown parsing.

---

## Root Structure (revised)

```
/memory-root/
├── _index.yaml                  # Root manifest — lists all projects (auto-managed)
├── _projects-index.json         # Fast-lookup project index (auto-managed)
├── _refs-index.json             # @ref / #tag / [[link]] index (auto-managed)
├── _global/
│   ├── _index.yaml
│   ├── people/
│   │   ├── _index.yaml
│   │   └── {person-slug}.md
│   └── companies/
│       ├── _index.yaml
│       └── {company-slug}.md
├── _templates/
│   ├── project-index.md         # Static template — copied to project as _guide.md
│   ├── project-meta.yaml
│   ├── person.md
│   ├── company.md
│   ├── knowledge-entry.md
│   └── meeting-note.md
└── projects/
    └── {project-slug}/
        ├── _guide.md            # Static folder guide (human-editable, not auto-managed)
        ├── _index.yaml          # Auto-managed manifest (not directly writable via MCP)
        ├── _meta.yaml
        ├── people.md
        ├── companies.md
        ├── decisions.md
        ├── knowledge/
        │   ├── _index.yaml
        │   └── {topic}.md
        ├── correspondence/
        │   ├── _index.yaml
        │   ├── email-threads.md
        │   ├── calls.md
        │   └── messages.md
        ├── updates/
        │   ├── _index.yaml
        │   └── YYYY-MM-DD.md
        ├── docs/
        │   ├── _index.yaml
        │   └── ...
        └── notes/
            ├── _index.yaml
            └── ...
```

---

## _index.yaml schema

```yaml
# Auto-managed by the MCP server. Edit descriptions via update_file_description tool.
last_updated: "2025-01-15"
stale: false
files:
  - name: "roadmap.md"
    description: "Product roadmap and milestone timeline extracted from planning sessions."
    read_when: "Planning next sprint or reviewing timeline commitments."
    stale_after: "After any major scope change."
  - name: "api-spec.md"
    description: "API contract summary from v2 spec document."
    read_when: "Before writing any integration code."
    stale_after: null
```

Root `_index.yaml` has a slightly different shape to hold project summaries rather than files.

---

## Proposed Changes

### Module 1: Data Models

#### [NEW] models.py
- `ProjectMeta` — _meta.yaml (id, slug, name, status, type, company, owner, team, tags, created, updated)
- `KnowledgeFrontmatter` — knowledge/ frontmatter (source, processed, method, model, prompt-ref)
- `ManifestEntry` — single entry in _index.yaml (name, description, read_when, stale_after)
- `FolderManifest` — full _index.yaml (last_updated, stale, files list)
- `RootManifestEntry` — project summary entry in root _index.yaml
- `ProjectsIndex` — _projects-index.json
- `RefsIndex` — _refs-index.json
- `ProjectStatus`, `ProjectType` — enums

---

### Module 2: Templates

#### [NEW] templates.py
String constants for all template files + the YAML manifest skeleton:
- `PROJECT_GUIDE_TEMPLATE` — static _guide.md with folder guide table (rendered once on project creation)
- `PROJECT_META_TEMPLATE` — blank _meta.yaml with field comments
- `PERSON_TEMPLATE` — name, title, company, contact, notes, projects
- `COMPANY_TEMPLATE` — name, industry, description, contacts, projects
- `KNOWLEDGE_ENTRY_TEMPLATE` — frontmatter block + placeholder sections
- `MEETING_NOTE_TEMPLATE` — date, attendees, agenda, notes, decisions, action items
- `EMPTY_MANIFEST` — base `_index.yaml` skeleton (used when scaffolding new folders)

---

### Module 3: Filesystem Engine

#### [NEW] filesystem.py
`MemoryFS(root: Path)` — all FS operations. No MCP coupling.

**Index management**
- `load_projects_index()` / `save_projects_index(data)`
- `load_refs_index()` / `save_refs_index(data)`
- `update_refs_for_file(rel_path, content)` — parse and update _refs-index.json entry

**Manifest management (YAML)**
- `load_manifest(folder)` → `FolderManifest`
- `save_manifest(folder, manifest)` — writes _index.yaml (NEVER called from write_file or read_file; only from manifest-aware operations)
- `add_manifest_entry(folder, entry)` — append a new ManifestEntry
- `update_manifest_entry(folder, filename, **kwargs)` — targeted field update in YAML
- `rebuild_manifest(folder)` — scans folder, adds missing entries with placeholders, removes entries for deleted files
- `mark_manifest_stale(folder)` — sets `stale: true` in the YAML

**Rule enforcement**
- `to_kebab_case(name)` → str (auto-corrects or raises)
- `validate_date(s)` → bool
- `is_append_only(path)` → bool (updates/*.md and decisions.md)
- `is_manifest(path)` → bool (blocks _index.yaml from write_file / append_to_file)
- `parse_refs(content)` → `{refs: [...], tags: [...], links: [...]}`
- `validate_knowledge_frontmatter(content)` → `(valid: bool, errors: list)`
- `warn_unresolved_refs(refs)` → `list[str]` (warnings only, not errors)

**Project operations**
- `scaffold_project(slug, meta, description?)` — creates full folder tree, writes _meta.yaml, _guide.md, all _index.yaml skeletons, core .md files (people.md, companies.md, decisions.md), updates root _index.yaml + _projects-index.json
- `mark_manifest_stale(folder)` — triggered after any write to that folder

**File I/O**
- `read_file(path)` → str (UTF-8, path safety)
- `write_file(path, content, description?, read_when?)` — kebab-case enforcement, blocks _index.yaml, blocks append-only files, updates refs, adds/updates manifest entry, marks stale
- `append_file(path, content)` — only allowed for append-only paths; updates refs; marks stale
- `soft_delete(path)` — moves to `_trash/{timestamp}_{filename}`, removes entry from manifest
- `search_files(keyword)` → `list[{path, line_no, line}]`

**Global entity operations**
- `create_person(slug, data, description?)` — writes file + updates _global/people/_index.yaml
- `create_company(slug, data, description?)` — writes file + updates _global/companies/_index.yaml
- `resolve_ref(slug)` → `(path, content)` — checks people then companies

---

### Module 4: MCP Server

#### [NEW] server.py
FastMCP server. `--root` CLI arg. Initializes root structure on first run.

**Filesystem tools (14):**

| Tool | Signature highlights | Key behavior |
|---|---|---|
| `list_projects` | `status?`, `type?`, `tags?` | Filter _projects-index.json |
| `get_project_context` | `slug` | Returns _meta.yaml + rendered _index.yaml |
| `get_folder_manifest` | `folder_path` | Reads _index.yaml → renders as formatted text |
| `read_file` | `path` | UTF-8 read; blocks _index.yaml direct reads (suggest get_folder_manifest instead) |
| `write_file` | `path`, `content`, `description?`, `read_when?` | All rules; updates refs + manifest entry |
| `append_to_file` | `path`, `content` | Append-only files only; updates refs |
| `create_project` | `slug`, `name`, `status`, `type`, `meta?`, `description?` | Full scaffold + indexes |
| `create_knowledge_entry` | `project_slug`, `topic`, `content`, `frontmatter`, `description?`, `read_when?` | Validates frontmatter; writes; updates manifest |
| `update_manifest` | `folder_path` | Rebuilds _index.yaml from current folder contents, placeholders for missing descriptions |
| `update_file_description` | `folder_path`, `filename`, `description`, `read_when?`, `stale_after?` | Targeted YAML entry update — the only way to change manifest descriptions via MCP |
| `resolve_ref` | `slug` | @slug → global file path + content |
| `get_refs_for` | `ref` | @slug/#tag/[[link]] → files list from _refs-index.json |
| `search_files` | `keyword`, `folder?` | Grep across .md files; interface identical to future semantic search |
| `delete_file` | `path` | Soft-delete to _trash/; removes manifest entry |
| `list_stale_manifests` | — | All folders with `stale: true` in _index.yaml |

**Global entity tools (4):**

| Tool | Signature highlights | Key behavior |
|---|---|---|
| `create_person` | `slug`, `name`, `...fields`, `description?` | Person file + _global/people/_index.yaml |
| `create_company` | `slug`, `name`, `...fields`, `description?` | Company file + _global/companies/_index.yaml |
| `get_person` | `slug` | Reads _global/people/{slug}.md |
| `get_company` | `slug` | Reads _global/companies/{slug}.md |

**Error/warning pattern:** All tools return `{"result": ..., "warnings": [...]}` or `{"error": "...", "warnings": [...]}`. No unhandled exceptions.

---

### Module 5: Pre-populated Templates

#### [NEW] `_templates/` (written to memory-root on first boot)
- `project-guide.md` — folder guide table (copied as _guide.md into each new project)
- `project-meta.yaml`
- `person.md`
- `company.md`
- `knowledge-entry.md`
- `meeting-note.md`

---

### Module 6: Documentation

#### [NEW] README.md
- Requirements + install instructions (`pip install -r requirements.txt`)
- CLI usage (`python server.py --root /path/to/memory-root`)
- Memory root initialization walkthrough
- Full tool reference table
- Example workflow: create project → add knowledge → update description → search
- Future RAG integration notes

---

## Filesystem Rules Enforcement Summary

| Rule | Where enforced |
|---|---|
| Kebab-case filenames | `write_file`, `create_*` |
| YYYY-MM-DD dates | `models.py` validators |
| updates/ and decisions.md append-only | `is_append_only()` in `write_file` |
| _index.yaml not directly writable | `is_manifest()` gate in `write_file` / `append_to_file` |
| knowledge/ frontmatter required | `create_knowledge_entry` + `write_file` path detection |
| @ref resolution warnings | `warn_unresolved_refs()` on every write |
| Unique project slugs | checked against _projects-index.json in `create_project` |
| _meta.yaml required before project is active | `get_project_context` warns if missing |

---

## Verification Plan

### Install & Boot
```powershell
pip install -r requirements.txt
python server.py --root ./test-memory
```

### Tool smoke tests (manual via MCP inspector or test script)
1. `create_project` → folder tree created, `_projects-index.json` updated
2. `write_file` with `description` → manifest entry populated in `_index.yaml`
3. `update_file_description` → targeted YAML update only
4. `append_to_file` on `decisions.md` → succeeds; same on `_index.yaml` → blocked
5. `write_file` to `_index.yaml` → blocked with clear error
6. `search_files("keyword")` → returns path + line number
7. `create_person` / `create_company` → global entities + _index.yaml updated
8. `delete_file` → moved to `_trash/`, not hard-deleted; manifest entry removed
9. `list_stale_manifests` → returns folders after untracked writes