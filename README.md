# Project Memory MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp)-based server that gives an LLM a structured, navigable filesystem for long-term project memory. Memory lives on plain disk as Markdown and YAML files — no database, no embeddings required. Designed to slot under a future RAG layer without schema changes.

---

## How it works

The server exposes a set of MCP tools that an LLM (e.g. Claude) calls to read, write, and navigate project memory. Every project gets a predictable folder layout:

```
projects/{slug}/
├── _status.md     ← always-current status: "as of today, blocked on X, next action is Y"
├── _guide.md      ← folder structure reference table
├── _meta.yaml     ← project metadata (status, type, owner, tags)
├── people.md      ← auto-managed linked people grouped by company
├── decisions.md   ← append-only decision log
├── knowledge/     ← processed knowledge entries with YAML frontmatter
├── updates/       ← chronological append-only update log
└── ...
```

Three auto-managed JSON/YAML indexes keep navigation fast:

| Index file | Purpose |
|---|---|
| `_index.yaml` (per folder) | Manifest: file descriptions + "read when" hints used by the LLM to decide what to load |
| `_projects-index.json` | Fast project listing with filter support |
| `_refs-index.json` | `@person`, `#tag`, `[[link]]` cross-reference index |

The `read_when` field in manifests is the key design element: it lets the LLM skip reading files it does not need, and is a first-class embedding target for a future RAG layer.

---

## Installation

```bash
pip install -r requirements.txt
```

Dependencies: `fastmcp>=2.0.0`, `pyyaml>=6.0`, `pydantic>=2.0`

---

## Usage

```bash
# Start with default memory root
python src/server.py --root ./memory-root

# HTTP transport (for HTTP-capable MCP clients)
python src/server.py --root ./memory-root --transport http --host 127.0.0.1 --port 8000
```

On first run the server creates the root structure automatically.

### Connecting to Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "project-memory": {
      "command": "python",
      "args": ["/absolute/path/to/src/server.py", "--root", "/absolute/path/to/memory-root"]
    }
  }
}
```

### Packaging the Claude Skill

This repository includes a Claude skill in [project-memory-mcp-skill](project-memory-mcp-skill).
To use it in Claude, package that folder as a zip and upload it in Claude's skill import UI.

Expected skill contents:
- [project-memory-mcp-skill/SKILL.md](project-memory-mcp-skill/SKILL.md)
- [project-memory-mcp-skill/references](project-memory-mcp-skill/references)

Create the zip from the repository root:

```powershell
# Windows PowerShell
Compress-Archive -Path .\skill\* -DestinationPath .\project-memory-mcp-skill.zip -Force
```

```bash
# macOS / Linux
cd skill
zip -r ../project-memory-mcp-skill.zip .
cd ..
```

Then upload the generated zip archive (for example, project-memory-mcp-skill.zip) to Claude.

### Debugging with MCP Inspector

Use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to interactively explore and test all tools from a browser UI:

```bash
npx @modelcontextprotocol/inspector python src/server.py --root ./memory-root
```

Then open `http://localhost:5173` to browse tools, call them with custom parameters, and inspect responses in real time.

If using a virtual environment, point to the environment's Python directly:

```bash
# Windows
npx @modelcontextprotocol/inspector .venv\Scripts\python.exe src/server.py --root ./memory-root

# macOS / Linux
npx @modelcontextprotocol/inspector .venv/bin/python src/server.py --root ./memory-root
```

---

## Quick example

```python
# Create a project
create_project(slug="my-api", name="My API Project", status="active", type="client")

# Load project context (status + meta + manifest in one call)
get_project_context(slug="my-api")

# Deep load also includes knowledge manifest + people
get_project_context(slug="my-api", deep=True)

# Search within a project
search_files(keyword="OAuth2", project_slug="my-api")

# Create a knowledge entry
create_knowledge_entry(
    project_slug="my-api",
    topic="auth-design",
    content="OAuth2 flow chosen over API keys.",
    frontmatter={"source": "meeting-2025-01-15", "processed": "2025-01-16", "method": "manual"},
)

# Add a decision (append-only)
append_to_file("projects/my-api/decisions.md",
               "\n## 2025-01-15 — Use OAuth2\n\nChosen for security compliance.")

# Create global entities and resolve references
create_person(slug="john-doe", name="John Doe", title="Lead Engineer", company="Other", global_description="Platform lead")
create_company(slug="acme-corp", name="ACME Corp")

# Establish a person-project relationship (updates global person projects + project people.md)
link_person_to_project(person_slug="john-doe", project_slug="my-api")

resolve_ref("john-doe")           # returns _global/people/john-doe.md
list_global_people()              # list all people without reading manifests manually
```

---

## Project structure

```
project-memory-mcp/
├── src/
│   ├── server.py        # MCP server entry point + tool definitions + resource
│   ├── filesystem.py    # All filesystem logic (MemoryFS class)
│   ├── guide.py         # memory://guide resource generator
│   ├── models.py        # Pydantic data models
│   └── templates.py     # Template strings for scaffolded files
├── tests/
│   ├── conftest.py      # sys.path setup for src/
│   └── tests.py         # Full test suite (130 tests)
├── docs/
│   ├── tool-reference.md       # Complete tool + resource reference
│   ├── memory-root-schema.md   # Every file/folder schema explained
│   └── filesystem-rules.md     # Enforcement rules and their triggers
├── README.md
└── requirements.txt
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/tool-reference.md](docs/tool-reference.md) | Every tool: parameters, behaviour, return shape; Resources section |
| [docs/memory-root-schema.md](docs/memory-root-schema.md) | Every file and folder schema (YAML examples included) |
| [docs/filesystem-rules.md](docs/filesystem-rules.md) | All enforced rules: what triggers them, error vs warning |

---

## Resources

| Resource | Description |
|---|---|
| `memory://guide` | Compact structural reference — read once per session before using any tool |

---

## Running tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

---

## Design notes

**Why plain files?**  
Plain Markdown and YAML files are human-readable, git-versionable, and require no migration when the schema evolves. An LLM can read and write them directly without an ORM or query language.

**Why `_index.yaml` instead of a database?**  
The manifest stores the `read_when` hint per file. This is the primary signal an LLM uses to decide what to load before starting a task — without it, every call would either read everything (slow, expensive) or read nothing (blind). Manifests also become the pre-filter for RAG retrieval: embed `description + read_when`, use the manifest to narrow the candidate set, then load only the relevant files.

**Why soft delete?**  
Files moved to `_trash/` are recoverable and maintain a full audit trail. Permanent deletion is an explicit on-disk action outside the MCP interface.

