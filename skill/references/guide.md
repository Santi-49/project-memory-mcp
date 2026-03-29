# Project Memory MCP — Server Guide
_Generated: 2026-03-29_
_Root: C:\Users\romag\Documents\claude-mcps\project-memory-mcp\memory-root_

## What this server manages
Structured project memory stored as Markdown and YAML files on plain disk.
Each project gets a predictable folder layout with manifests, metadata, and
processed knowledge entries. No database or embeddings required.

## Root structure
```
memory-root/
├── _global
│   ├── _index.yaml
│   ├── companies
│   └── people
├── _index.yaml  [auto]
├── _projects-index.json  [auto]
├── _refs-index.json  [auto]
├── _templates
│   ├── company.md
│   ├── knowledge-entry.md
│   ├── person.md
│   ├── project-guide.md
│   └── project-meta.yaml
├── _trash  (soft-deleted files)
└── projects
    └── {slug}
```
Legend:
  [auto]   — managed by server, never edit directly
  [human]  — scaffolded by server, edit freely
  [append] — append-only, use append_to_file tool

## Project folder layout
```
projects/{slug}/
├── _status.md          [human]  Always-current status — first loaded in get_project_context
├── _guide.md           [human]  Folder structure reference table
├── _index.yaml         [auto]   Folder manifest with read_when hints per file
├── _meta.yaml          [human]  Project metadata
├── people.md           [auto]   Project people grouped by company (from global links)
├── companies.md                 Company relationships
├── decisions.md        [append] Architecture and key decision log
├── knowledge/                   LLM-processed entries (require YAML frontmatter)
├── correspondence/              Email summaries, call notes, messages
├── updates/            [append] Chronological date-stamped update log
├── docs/                        Raw reference documents
└── notes/                       Free-form scratchpad
```

## Folder routing rules
Use this decision table when choosing where new information belongs.

| Need | Write to |
|---|---|
| Current status and immediate next step | `_status.md` |
| Metadata and ownership fields | `_meta.yaml` |
| Durable decision and rationale | `decisions.md` (append-only) |
| Processed reusable knowledge | `knowledge/{topic}.md` (with frontmatter) |
| Chronological project log/event trail | `updates/{date-or-topic}.md` (append-only) |
| Email thread summaries | `correspondence/email-threads.md` |
| Meeting/call summaries | `correspondence/calls.md` |
| Chat message summaries | `correspondence/messages.md` |
| External specs / source docs | `docs/*` |
| Temporary working notes / drafts | `notes/*` |
| Stakeholder links by person/company | `people.md` (auto-managed), `companies.md` |

If unsure between folders:
- Prefer `knowledge/` for evergreen facts likely reused later.
- Prefer `updates/` for time-ordered progress notes.
- Prefer `notes/` only for transient draft material.

## Tool inventory

### Filesystem tools
| Tool | Required params | Description |
|---|---|---|
| `add_sync_source` | project_slug, source_type, id, label | Register a new M365 source for a project |
| `append_to_file` | path, content | Append content to an append-only file (`updates/*.md` or `decisions.md`) |
| `create_knowledge_entry` | project_slug, topic, content, frontmatter | Create a knowledge entry with validated frontmatter in `projects/{slug}/knowledge/` |
| `create_project` | slug, name | Create a new project with full folder scaffold |
| `delete_file` | path | Soft-delete a file (move to `_trash/`). Removes manifest entry |
| `delete_project` | slug, confirm | Soft-delete an entire project. Must set `confirm=true` |
| `get_folder_manifest` | folder_path | Read `_index.yaml` for a folder and render as formatted text |
| `get_project_context` | slug | Return project context |
| `get_refs_for` | ref | Return all files that mention `@ref`, `#tag`, or `[[link]]` |
| `get_related_files` | path | Return bidirectional cross-reference map for a file |
| `get_sync_state` | project_slug | Read `_sync.yaml` for a project |
| `list_projects` | status, type, tags | List all projects, optionally filtered |
| `list_projects_due_for_sync` | frequency | Return projects where a sync run is overdue |
| `list_projects_due_for_synthesis` | — | Return projects where a knowledge synthesis run is overdue |
| `list_stale_manifests` | — | Return all folder paths where `_index.yaml` has `stale: true` |
| `read_file` | path | Read a file. Blocks direct reads of `_index.yaml` and `_sync.yaml` |
| `resolve_m365_ref` | project_slug, ref | Resolve an M365 reference token to its full metadata |
| `resolve_ref` | slug | Resolve `@slug` to a global entity (person or company) and return its content |
| `search_files` | keyword | Search `.md` files for keyword |
| `update_file_description` | folder_path, filename, description | Targeted update of a manifest entry |
| `update_manifest` | folder_path | Rebuild `_index.yaml` for a folder |
| `update_project` | slug | Update a project's metadata |
| `update_sync_state` | project_slug, source_type, source_id, fields | Update watermark fields after pipeline processing |
| `write_file` | path, content | Write a file with all rules enforced (kebab-case, append-only blocks, manifest update) |

### Global entity tools
| Tool | Required params | Description |
|---|---|---|
| `create_company` | slug, name | Create a company file in `_global/companies/` |
| `create_person` | slug, name | Create a global person profile |
| `edit_person_notes` | slug, notes | Edit manual notes in a global person profile |
| `get_company` | slug | Read a company file |
| `get_person` | slug | Read a person file |
| `link_person_to_project` | person_slug, project_slug | Create a person-project relationship |
| `list_global_companies` | — | List all companies |
| `list_global_people` | — | List all people |
| `rebuild_refs_index` | — | Rebuild `_refs-index.json` by scanning all `.md` files |
| `unlink_person_from_project` | person_slug, project_slug | Remove a person-project relationship |
| `update_company` | slug | Update structured fields for a company |
| `update_person` | slug | Update structured fields for a person |

## Reference syntax
Use these tokens anywhere in Markdown file bodies or frontmatter fields.
Parsed and indexed by the server on every write.

| Token | Resolves to |
|---|---|
| `@person-slug` | `_global/people/{slug}.md` |
| `@company-slug` | `_global/companies/{slug}.md` |
| `#tag` | canonical list in `_global/tags.md` |
| `[[project-slug]]` | `projects/{slug}/` |
| `[mem:projects/proj/notes/x.md]` | internal cross-reference to another workspace file |
| `[sp:source-id/path]` | SharePoint document (registered in `_sync.yaml`) |
| `[tm:source-id/message-id]` | Teams message (registered in `_sync.yaml`) |
| `[ol:source-id/message-id]` | Outlook email (registered in `_sync.yaml`) |

Unresolved `@refs` and unresolved `[mem:]` refs produce warnings, not errors.
File is still written — warnings are returned in the tool response.

knowledge/ entries may list multiple sources in frontmatter:
```yaml
source: "[sp:sp-contracts/msa-v2.pdf]"        # single source
source:                                         # multiple sources
  - "[sp:sp-contracts/msa-v2.pdf]"
  - "[mem:projects/acme/correspondence/q1-thread.md]"
```

## Key schemas

### _meta.yaml
```yaml
id, slug, name,
status: active | paused | completed | archived
type: client | internal | research | personal
company: @slug
owner: @slug
team: [@slug]
tags: [str]
created: YYYY-MM-DD
updated: YYYY-MM-DD
```

### knowledge/ frontmatter (required on every knowledge entry)
```yaml
source: str | [str] | null   # M365 ref, [mem:] path, plain text, or list
processed: YYYY-MM-DD
method: manual | summary | extract
model: str
prompt_ref: str
```

### _index.yaml entry (auto-managed — edit via update_file_description)
```yaml
name, description, read_when, stale_after
```

## Filesystem rules

Best practice before mutating existing content:
- Read current content first (`get_person`, `get_company`, `get_project_context`, `read_file`)
- Then apply targeted updates to avoid unintentionally overwriting newer notes or fields
- Before `create_person`/`create_company`, check existing entities first (`list_global_people`/`list_global_companies`)

| Rule | Trigger | Severity |
|---|---|---|
| Destructive operations — ask user first | `delete_project` | Ask User First |
| Path must stay inside memory root | Any path argument | Error |
| Filenames must be kebab-case | `write_file`, `create_*` | Error |
| `updates/` and `decisions.md` append-only | `write_file` (use `append_to_file` instead) | Error |
| `_index.yaml` not writable or readable | `write_file`, `append_to_file`, `read_file` | Error |
| `projects/*/people.md` is auto-managed | `write_file`, `delete_file` | Error |
| Knowledge entries require frontmatter | `write_file` on `knowledge/*.md` | Warning |
| Unresolved `@ref` tokens | `write_file`, `append_to_file` | Warning |
| Unresolved `[mem:path]` tokens | `write_file`, `append_to_file` | Warning |
| Project slugs must be unique | `create_project` | Error |
| Dates must be YYYY-MM-DD | Pydantic model validation | Error |

## Project memory as source of truth

Once knowledge is processed and stored in the project memory filesystem, treat it
as your source of truth. This avoids redundant M365 calls and conserves tokens.

### Local-first principle

1. **Read from memory first.** Before pulling data from SharePoint, Teams, or Outlook,
   check if it's already summarized in:
   - `projects/{slug}/knowledge/` — processed, indexed knowledge
   - `projects/{slug}/updates/` — chronological project timeline
   - `projects/{slug}/correspondence/*` — email/call/message summaries
   - `projects/{slug}/decisions.md` — settled decisions with rationale

2. **Avoid re-processing.** If a file has already been summarized and stored with
   a source reference (e.g., `source: [sp:sp-contracts/msa-v2.pdf]`), do not
   fetch and re-process the same source later. Instead:
   - Call `read_file` on the knowledge entry
   - Use `get_project_context` to load the summary into conversation
   - Reference the local summary when answering questions

3. **Token efficiency.** Network waterfalls (fetch from M365 → summarize → store)
   are expensive. Once the summary is stored, the local Markdown file is your
   canonical reference. Reuse it across sessions and calls.

4. **Trust the processed metadata.** The `source:`, `processed:`, and `method:` fields
   in knowledge entry frontmatter tell you exactly what you're looking at, when it
   was processed, and how. Trust this metadata over re-fetching the source.

### When to pull fresh from M365

Re-pull from M365 sources only when:
- The local entry is explicitly marked `stale_after: YYYY-MM-DD` and that date has passed
- A user asks for updates to stale content ("What's changed since March?")
- The source is newly registered and has never been processed before
- You are asked to validate against a live source (rare, for compliance/audit only)

### Reference pattern for processed content

When citing processed knowledge, always include the local reference:
  "According to our processed notes (from [sp:sp-contracts/msa-v2.pdf]),
   the contract term is 24 months."

This pattern:
- Maintains auditability (reader can trace back to original)
- Signals that this is a processed summary, not the raw source
- Reduces risk of stale data (frontmatter shows last processed date)
