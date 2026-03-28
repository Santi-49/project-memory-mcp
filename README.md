# Project Memory MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp)-based server that manages a structured project memory filesystem using Markdown and YAML files on plain disk. Designed to support a future RAG layer without schema changes.

---

## Requirements & Installation

```bash
pip install -r requirements.txt
```

**Dependencies:**
- `fastmcp>=2.0.0` — MCP server framework
- `pyyaml>=6.0` — YAML parsing and serialisation
- `pydantic>=2.0` — Data validation

---

## CLI Usage

```bash
# Start with default memory-root in current directory
python server.py --root ./memory-root

# Custom path
python server.py --root /home/user/project-memory

# HTTP transport (for use with HTTP-capable MCP clients)
python server.py --root ./memory-root --transport http --host 127.0.0.1 --port 8000
```

On first run, the server automatically initialises the root structure:

```
memory-root/
├── _index.yaml                  # Root manifest (auto-managed)
├── _projects-index.json         # Fast-lookup project index (auto-managed)
├── _refs-index.json             # @ref / #tag / [[link]] index (auto-managed)
├── _global/
│   ├── _index.yaml
│   ├── people/
│   │   └── _index.yaml
│   └── companies/
│       └── _index.yaml
├── _templates/                  # Reference template files
├── _trash/                      # Soft-deleted files land here
└── projects/                    # Project folders created here
```

---

## Memory Root Structure

Each project lives at `projects/{project-slug}/` with the following layout:

```
projects/my-project/
├── _guide.md            # Static folder guide (human-editable)
├── _index.yaml          # Auto-managed manifest — use get_folder_manifest
├── _meta.yaml           # Project metadata
├── people.md            # Key contacts
├── companies.md         # Company relationships
├── decisions.md         # Decision log (append-only)
├── knowledge/           # Processed knowledge entries
├── correspondence/      # Emails, calls, messages
├── updates/             # Date-stamped updates (append-only)
├── docs/                # Reference documents
└── notes/               # Free-form notes
```

> **Important:** Never write to `_index.yaml` directly. Always use `update_file_description` or `update_manifest`.

---

## Tool Reference

### Filesystem Tools

| Tool | Parameters | Description |
|---|---|---|
| `list_projects` | `status?`, `type?`, `tags?` | List all projects; optional filters |
| `get_project_context` | `slug` | Returns `_meta.yaml` content + rendered `_index.yaml` |
| `get_folder_manifest` | `folder_path` | Renders `_index.yaml` as human-readable text |
| `read_file` | `path` | UTF-8 file read; blocks `_index.yaml` direct reads |
| `write_file` | `path`, `content`, `description?`, `read_when?` | Write with rule enforcement + manifest update |
| `append_to_file` | `path`, `content` | Append to `updates/*.md` or `decisions.md` only |
| `create_project` | `slug`, `name`, `status?`, `type?`, `meta?`, `description?` | Full project scaffold |
| `create_knowledge_entry` | `project_slug`, `topic`, `content`, `frontmatter`, `description?`, `read_when?` | Knowledge entry with frontmatter validation |
| `update_manifest` | `folder_path` | Rebuild `_index.yaml` from current folder contents |
| `update_file_description` | `folder_path`, `filename`, `description`, `read_when?`, `stale_after?` | Targeted manifest entry update |
| `resolve_ref` | `slug` | `@slug` → global entity path + content |
| `get_refs_for` | `ref` | `@slug`/`#tag`/`[[link]]` → list of files that mention it |
| `search_files` | `keyword`, `folder?` | Full-text search across `.md` files |
| `delete_file` | `path` | Soft-delete to `_trash/`; removes manifest entry |
| `list_stale_manifests` | — | All folders with `stale: true` in `_index.yaml` |

### Global Entity Tools

| Tool | Parameters | Description |
|---|---|---|
| `create_person` | `slug`, `name`, `title?`, `company?`, `email?`, `phone?`, `description?` | Create person in `_global/people/` |
| `create_company` | `slug`, `name`, `industry?`, `website?`, `description?` | Create company in `_global/companies/` |
| `get_person` | `slug` | Read `_global/people/{slug}.md` |
| `get_company` | `slug` | Read `_global/companies/{slug}.md` |

### Response Format

All tools return:
```json
{"result": ..., "warnings": [...]}
```
or on error:
```json
{"error": "...", "warnings": [...]}
```

No unhandled exceptions are raised.

---

## Example Workflow

```python
# 1. Create a project
create_project(slug="my-api", name="My API Project", status="active", type="client",
               description="Main API integration project for ACME Corp.")

# 2. Add a knowledge entry
create_knowledge_entry(
    project_slug="my-api",
    topic="auth-design",
    content="OAuth2 flow chosen over API keys for better security.",
    frontmatter={"source": "meeting-2025-01-15", "processed": "2025-01-16", "method": "manual"},
    description="OAuth2 authentication design decision.",
    read_when="Before implementing any auth-related code.",
)

# 3. Update a file description after writing
write_file("projects/my-api/people.md", "# People\n\n@john-doe — Lead engineer")
update_file_description("projects/my-api", "people.md",
                        description="Key stakeholders on the My API project.",
                        read_when="Before any meeting or communication.")

# 4. Search across all notes
search_files("OAuth2")

# 5. Create global entities
create_person(slug="john-doe", name="John Doe", title="Lead Engineer", email="john@acme.com")
create_company(slug="acme-corp", name="ACME Corp", industry="Technology")

# 6. Add a project decision (append-only)
append_to_file("projects/my-api/decisions.md",
               "\n## 2025-01-15 — Use OAuth2\n\nChosen for security and industry standard compliance.")

# 7. Find stale manifests
list_stale_manifests()
```

---

## Filesystem Rules

| Rule | Enforcement |
|---|---|
| Kebab-case filenames | `write_file`, `create_*` |
| YYYY-MM-DD dates | Pydantic validators in `models.py` |
| `updates/` and `decisions.md` append-only | `is_append_only()` check in `write_file` |
| `_index.yaml` not directly writable | `is_manifest()` gate in `write_file` / `append_to_file` |
| Knowledge frontmatter required | `create_knowledge_entry` + path detection in `write_file` |
| `@ref` resolution warnings | `warn_unresolved_refs()` on every write |
| Unique project slugs | Checked against `_projects-index.json` in `create_project` |
| `_meta.yaml` required | `get_project_context` warns if missing |

---

## `_index.yaml` Schema

```yaml
# Auto-managed by the MCP server. Edit descriptions via update_file_description tool.
last_updated: "2025-01-15"
stale: false
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

---

## Future RAG Integration

`_index.yaml` files are the primary metadata pre-filter for query routing. The `read_when` field is a first-class embedding target — it allows a RAG layer to route queries to the right folder without needing to embed or scan every file.

Planned integration points:
- Embed `description` + `read_when` fields at index-build time
- Use `_projects-index.json` as a fast project pre-filter
- `_refs-index.json` enables cross-file link traversal at query time
