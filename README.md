# Project Memory MCP Server

> Structured, disk-based project memory for enterprise LLMs. Seamless M365 integration. Zero database.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.0%2B-brightgreen.svg)](https://github.com/jlowin/fastmcp)

---

## The Problem

**Enterprise teams lose institutional knowledge.** Project context lives scattered across:
- Email threads (Outlook) — hard to search, tied to individuals
- SharePoint documents — version-controlled but siloed
- Teams messages — ephemeral, context-dependent
- Meeting notes — often forgotten or stuck in personal notebooks
- Decisions and architecture — rarely documented, often re-discussed

When an LLM needs to understand a project, it either:
- Reads everything (slow, expensive, noisy) 
- Reads nothing (useless, blind)
- Re-syncs M365 sources repeatedly (wastes quotas and tokens)

**Project Memory MCP solves this:** Treat your project memory as a **single source of truth** — one central place where all knowledge lives, processed once, reused forever.

---

## The Solution

**Enterprise teams need:**

- ✅ **Local-first knowledge** — Process M365 sources once, store summaries locally, avoid re-fetching
- ✅ **Structured memory** — Predictable, navigable folder layout that LLMs understand
- ✅ **M365 sync** — Automatic or manual ingestion from Outlook, Teams, SharePoint
- ✅ **Token efficiency** — Manifest-based `read_when` hints guide LLMs to load only what's needed
- ✅ **Human readable and editable** — Plain Markdown and YAML files, no proprietary formats, edit in any text editor
- ✅ **Full control** — Plain files on disk, no vendor lock-in, git-versionable
- ✅ **Zero database** — No migrations, no ORM, no complex schemas

**Project Memory MCP** is a [Model Context Protocol](https://modelcontextprotocol.io/) server that enables LLMs (especially Claude) to maintain and query structured project memory integrated with M365.

### How it works

Every project organizes as a **navigable folder hierarchy** on plain disk:

```
projects/databuddy/
├── _status.md        # Current blockers, wins, next steps (read first)
├── decisions.md      # Append-only decision log with rationale
├── knowledge/        # Processed knowledge from M365 sources
│   ├── deployment.md       # [sp:sp-contracts/deployment-reqs.pdf]
│   └── architecture.md     # Generated from [tm:teams-arch/msg-123]
├── correspondence/   # Summaries of emails, calls, messages
├── updates/          # Chronological change log (append-only)
└── people.md         # Team members (auto-updated from global links)
```

**Key innovation:** Every knowledge entry stores **where it came from**:
```yaml
source: "[sp:sp-contracts/deployment-reqs.pdf]"  # Points back to SharePoint
processed: 2026-03-29
method: summary
```

LLMs read the local summary instead of re-fetching. Token costs drop by 80%+.

---

## Built for M365 + LLM Workflows

**Three integration patterns:**

1. **Automated sync pipeline** — Scheduled job reads M365, summarizes via LLM, stores locally
2. **Manual fetch** — LLM calls M365 MCP when needed, processes, stores result
3. **Hybrid** — Mix of both (most common)

All patterns feed knowledge into the same local store. Once processed, the LLM uses only the local summary.

---

## M365 integration

The server tracks sources from three M365 services:

**Automatic sync pipeline** — Scheduled job on a dedicated VM:
1. Reads from Outlook (emails, threads)
2. Reads from Teams (channels, messages)
3. Reads from SharePoint (documents, libraries)
4. Summarizes via Claude API
5. Stores locally with source reference

**Manual fetch** — LLM-initiated (on demand):
1. LLM calls M365 MCP to fetch raw content
2. LLM processes and summarizes
3. LLM stores via memory MCP with source tracking

**Result:** All M365 data is indexed and never re-fetched. After first processing, the LLM uses only the local summary.

---

## Installation

```bash
pip install -r requirements.txt
python src/server.py
```

**Requirements:** Python 3.13+, `fastmcp>=2.0.0`, `pyyaml>=6.0`, `pydantic>=2.0`

---

## Quick start

### 1. Install

```bash
pip install -r requirements.txt
python src/server.py  # Starts on default ./memory-root
```

### 2. Connect to Claude

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "project-memory": {
      "command": "python",
      "args": ["/path/to/src/server.py"]
    }
  }
}
```

### 3. Try the MCP Inspector

```bash
npx @modelcontextprotocol/inspector python src/server.py
# Visit http://localhost:5173
```

---

## Core Features

### 1. Structured project memory

Every project is a folder with predictable structure:

| Element | Purpose |
|---|---|
| `_status.md` | Always-current status (read first by LLM) |
| `decisions.md` | Append-only decision log |
| `knowledge/` | Processed knowledge from M365 or manual entry |
| `correspondence/` | Email, call, message summaries with dates |
| `updates/` | Chronological changelog (append-only) |
| `people.md` | Team members (auto-generated from links) |

### 2. M365 source tracking

Every knowledge entry points back to its source:

```yaml
source: "[sp:sp-contracts/msa.pdf]"  # SharePoint file
        # or "[tm:teams-sales/msg-123]"  # Teams message
        # or "[ol:outlook-sales/thread-456]"  # Outlook email
processed: 2026-03-29
method: summary
```

LLMs use the local summary. No re-fetching. Saves 80%+ in tokens.

### 3. Auto-managed cross-references

The server maintains three indexes:

| Index | What it tracks |
|---|---|
| `_index.yaml` | File descriptions + `read_when` hints (per folder) |
| `_projects-index.json` | Fast project listing |
| `_refs-index.json` | `@person`, `@company`, `[[link]]` references |

### 4. Smart manifest hints

The `read_when` field guides LLM loading:

```yaml
knowledge/deployment.md:
  description: "Deployment requirements and SLA"
  read_when: "When planning releases or understanding constraints"
```

LLMs skip files they don't need → cheaper, faster.

### 5. Full-text RAG indexing

All project files (except `_index.yaml`) are automatically indexed using TF-IDF (or embeddings) 
for fast semantic search:

```json
{
  "_rag_index.json": {
    "docs": {
      "projects/databuddy/knowledge/architecture.md": {
        "tf": { "snowflake": 0.045, "migration": 0.032, ... },
        "mtime": 1774796858.3323283,
        "indexed_at": "2026-03-29T18:49:17.855188+00:00"
      }
    }
  }
}
```

**Every file in these directories is automatically indexed and searchable:**

| Directory | Indexed | Purpose |
|---|---|---|
| `_global/people/` | ✅ All `.md` files | Team member profiles (auto-indexed) |
| `_global/companies/` | ✅ All `.md` files | Partner and client information |
| `projects/{slug}/knowledge/` | ✅ All `.md` files | Processed knowledge and summaries |
| `projects/{slug}/correspondence/` | ✅ All `.md` files | Email, call, and message digests |
| `projects/{slug}/updates/` | ✅ All `.md` files | Chronological project updates |
| `projects/{slug}/decisions.md` | ✅ Single file | Decision log (append-only) |
| `_index.yaml` files | ❌ Never | Auto-managed manifests (excluded) |

Indexes are updated automatically when files change. Use the index for:
- **Semantic search** — Find relevant context by meaning, not keywords
- **Link discovery** — Understand what's related without reading everything  
- **Context routing** — Route LLM queries to the most relevant files
- **Token efficiency** — Read only what matters for the current task

---

## Documentation

The server includes **5 built-in MCP resources** (served automatically):

| Resource | Purpose |
|---|---|
| `memory://quick-reference` | Token syntax, filesystem rules, parameters |
| `memory://guide` | Complete server guide and tool inventory |
| `memory://m365` | M365 sync pipeline and source registration |
| `memory://skill` | Pre-flight checklist for new users |
| `memory://new-project` | 12-step project setup walkthrough |

All resources live in `skill/` and auto-update when you edit them.

---

## Project structure

```
project-memory-mcp/
├── src/
│   ├── server.py              # MCP server + tools + resources
│   ├── filesystem.py          # MemoryFS class + all file operations
│   ├── guide.py               # Resource generators
│   ├── models.py              # Pydantic data models for all schemas
│   └── templates.py           # Template strings for scaffolded files
├── skill/                     # Claude skill documentation (upload as .zip)
│   ├── SKILL.md               # Skill frontmatter + pre-flight checklist
│   └── references/
│       ├── quick-reference.md # Token syntax, filesystem rules, parameters
│       ├── guide.md           # Server guide, tool inventory, folder routing
│       ├── m365-guide.md      # M365 sync pipeline and integration
│       └── creating-new-project.md  # 12-step project setup guide
├── scripts/
│   └── migrate_newlines.py    # Fix escaped newlines in markdown files (one-time use)
├── tests/
│   ├── conftest.py            # Test configuration
│   └── tests.py               # Full test suite (130+ tests)
├── docs/
│   ├── tool-reference.md      # Complete tool reference (legacy, see skill/ instead)
│   ├── memory-root-schema.md  # File/folder schemas with examples
│   └── filesystem-rules.md    # Enforcement rules and triggers
├── memory-root/               # Example projects and global entities
├── README.md
├── LICENSE                    # MIT License
└── requirements.txt
```

---

## Documentation

Primary documentation is now in the `skill/` folder as **Markdown resources** that are automatically served by the server:

| Resource | Read from | Topic |
|---|---|---|
| `memory://quick-reference` | `skill/references/quick-reference.md` | Token syntax, filesystem rules, tool parameters |
| `memory://guide` | `skill/references/guide.md` | Complete server guide, folder routing, tool inventory |
| `memory://m365` | `skill/references/m365-guide.md` | M365 sync pipeline, source registration, reference syntax |
| `memory://skill` | `skill/SKILL.md` | Pre-flight checklist for new users |
| `memory://new-project` | `skill/references/creating-new-project.md` | 12-step project initialization walkthrough |

Reference documentation (kept for backwards compatibility):

| Document | Contents |
|---|---|
| [docs/tool-reference.md](docs/tool-reference.md) | Tool parameters and return shapes (superseded by resources) |
| [docs/memory-root-schema.md](docs/memory-root-schema.md) | File and folder schema definitions with YAML examples |
| [docs/filesystem-rules.md](docs/filesystem-rules.md) | Enforcement rules: what triggers errors vs. warnings |

---

## Packaging the Claude Skill

The `skill/` folder is a standalone Claude skill. To use it with Claude:

**Step 1: Create the ZIP archive**

```powershell
# Windows PowerShell
Compress-Archive -Path .\skill\* -DestinationPath .\project-memory-mcp-skill.zip -Force
```

```bash
# macOS / Linux
cd skill && zip -r ../project-memory-mcp-skill.zip . && cd ..
```

**Step 2: Upload to Claude**

1. Go to Claude.ai
2. Open settings (⚙️) → Manage custom skills
3. Click "Create skill" → Upload ZIP
4. Select the generated `project-memory-mcp-skill.zip`

The skill is now available in all Claude conversations.

---

## Data maintenance

### Fix escaped newlines (one-time migration)

If you accidentally write files with escaped newline sequences (`\n` instead of actual newlines):

```bash
python scripts/migrate_newlines.py --dry-run  # Preview changes
python scripts/migrate_newlines.py              # Apply fixes
```

The normalization also runs automatically on all `write_file` and `append_to_file` operations going forward.

---

## Testing

```bash
# Install test dependencies
pip install -r requirements.txt pytest

# Run all tests
python -m pytest tests/ -v

# Run specific test suite
python -m pytest tests/tests.py::TestGuideResource -v

# Run with coverage
python -m pytest tests/ --cov=src
```

---

## Architecture & Design

### Why plain files?

Plain Markdown and YAML files are:
- **Human-readable** — edit or read directly in any text editor
- **Git-versionable** — full audit trail, easy collaboration
- **Schema-stable** — no database migrations when requirements change
- **LLM-native** — Claude can read and write them directly

### Why `_index.yaml` manifests?

The manifest stores the `read_when` hint per file. This is the primary signal an LLM uses to decide what to load:

- **Without manifests**: Every call either reads everything (slow, expensive) or reads nothing (blind)
- **With manifests**: LLM skips files it doesn't need, reducing latency and token cost
- **RAG-compatible**: Manifests become the pre-filter for semantic search — embed `description + read_when`, narrow the set, load only relevant files

### Why soft delete (`_trash/`)?

Files moved to `_trash/` are:
- **Recoverable** — restore files that were deleted by mistake
- **Auditable** — full history of what was removed and when
- **Reversible** — unlike permanent deletion, this is an MCP operation (no disk-level action required)

### Why token optimization?

The server is designed to minimize token usage:

1. **Manifests guide loading** — LLMs use `read_when` hints to skip unnecessary files
2. **Local-first principle** — Store processed knowledge locally; avoid re-fetching same M365 content
3. **Quick reference** — Consolidated `memory://quick-reference` resource replaces scattered documentation
4. **Append-only logs** — Only changed entries are re-read, not entire files

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please include tests for new functionality and update documentation as needed.

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) file for details.

MIT License grants you the freedom to use, modify, and distribute this software for any purpose, with or without modification, under the simple condition that you include the original license and copyright notice in any copies or substantial portions of the software.

---

## Support

- **GitHub Issues** — Report bugs or request features [here](../../issues)
- **Discussions** — Ask questions or share ideas [here](../../discussions)
- **Documentation** — See the `skill/` guides for detailed reference material

---

## Acknowledgments

Built with [FastMCP](https://github.com/jlowin/fastmcp) and designed for [Claude](https://claude.ai) by Anthropic.

---

**Made with ❤️ for LLM-assisted project management**

