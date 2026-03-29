"""Generates the memory://guide MCP resource.

``generate_guide(mcp, root)`` is the single public entry-point.
All static section bodies are module-level string constants so they can be
updated in isolation without touching the generation logic.

Sections
--------
1. Header          – dynamic (date + root path)
2. What this server manages – static
3. Root structure  – dynamic (live filesystem walk, 2 levels deep)
4. Project folder layout – static
5. Tool inventory  – dynamic (derived from registered FastMCP tools)
6. Reference syntax – static
7. Key schemas     – static
8. Filesystem rules – static
9. Footer          – static
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fastmcp


# ---------------------------------------------------------------------------
# Static section constants
# ---------------------------------------------------------------------------

_SECTION_WHAT_THIS_MANAGES = """\
## What this server manages

Structured project memory stored as Markdown and YAML files on plain disk.
Each project gets a predictable folder layout with manifests, metadata, and
processed knowledge entries. No database or embeddings required."""

_SECTION_PROJECT_LAYOUT = """\
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
```"""

_SECTION_REF_SYNTAX = """\
## Reference syntax

Use these tokens anywhere in Markdown file bodies.
Parsed and indexed by the server on every write.

  @person-slug       → resolves to _global/people/{slug}.md
  @company-slug      → resolves to _global/companies/{slug}.md
  #tag               → canonical list in _global/tags.md
  [[project-slug]]   → resolves to projects/{slug}/

Unresolved @refs produce warnings, not errors. File is still written.
Create the entity first with create_person or create_company to silence them."""

_SECTION_KEY_SCHEMAS = """\
## Key schemas

### _meta.yaml
id, slug, name, status (active|paused|completed|archived),
type (client|internal|research|personal), company (@slug),
owner (@slug), team ([@slug]), tags ([str]), created, updated

### knowledge/ frontmatter (required on every knowledge entry)
source, processed (YYYY-MM-DD), method (manual|summary|extract),
model, prompt_ref

### _index.yaml entry (auto-managed — edit via update_file_description)
name, description, read_when, stale_after

### _status.md frontmatter (optional but recommended for RAG freshness)
last_updated: YYYY-MM-DD"""

_SECTION_FS_RULES = """\
## Filesystem rules

Best practice before mutating existing content:
- Read current content first (for example get_person, get_company, get_project_context, read_file)
- Then apply targeted updates to avoid unintentionally overwriting newer notes or fields
- Before create_person/create_company, check existing entities first (list_global_people/list_global_companies)

Rule                                    Trigger                         Severity
──────────────────────────────────────  ──────────────────────────────  ────────
Destructive operations (delete, etc)    delete_project                  Ask User First
Path must stay inside memory root       Any path argument               Error
Filenames must be kebab-case            write_file, create_*            Error
updates/ and decisions.md append-only   write_file (use append instead) Error
_index.yaml not writable or readable    write_file, append, read_file   Error
projects/*/people.md is auto-managed    write_file, delete_file          Error
Knowledge entries require frontmatter   write_file on knowledge/*.md    Warning
Unresolved @ref tokens                  write_file, append_to_file      Warning
Project slugs must be unique            create_project                  Error
Dates must be YYYY-MM-DD                Pydantic model validation       Error"""

_SECTION_FOOTER = """\
---
Full parameter reference:  docs/tool-reference.md
Full schema reference:     docs/memory-root-schema.md
Enforcement details:       docs/filesystem-rules.md"""

# ---------------------------------------------------------------------------
# Known tool groups (used only for section headings — tool names/descriptions
# are always derived from the live FastMCP instance at call time)
# ---------------------------------------------------------------------------

_GLOBAL_ENTITY_TOOLS: frozenset[str] = frozenset(
    {
        "create_person",
        "create_company",
        "update_person",
        "edit_person_notes",
        "update_company",
        "link_person_to_project",
        "unlink_person_from_project",
        "get_person",
        "get_company",
        "list_global_people",
        "list_global_companies",
        "rebuild_refs_index",
    }
)


# ---------------------------------------------------------------------------
# Dynamic section generators
# ---------------------------------------------------------------------------


def _section_header(root: Path) -> str:
    today = date.today().isoformat()
    return f"# Project Memory MCP — Server Guide\n_Generated: {today}_\n_Root: {root}_"


def _annotate(name: str) -> str:
    """Return a short annotation comment for well-known root-level names."""
    _annotations: dict[str, str] = {
        "_index.yaml": "[auto]",
        "_projects-index.json": "[auto]",
        "_refs-index.json": "[auto]",
        "_global": "",
        "_templates": "",
        "_trash": "(soft-deleted files)",
        "projects": "",
    }
    return _annotations.get(name, "")


def _section_root_structure(root: Path) -> str:
    """Walk the memory root up to 2 levels deep and build a tree string."""
    lines: list[str] = ["## Root structure", ""]
    if not root.exists():
        lines.append("_(memory root not yet initialised)_")
        lines.append("")
        lines.append(
            "Legend:\n  [auto]   — managed by server, never edit directly\n"
            "  [human]  — scaffolded by server, edit freely\n"
            "  [append] — append-only, use append_to_file tool"
        )
        return "\n".join(lines)

    lines.append(f"{root.name}/")
    top_items = sorted(
        root.iterdir(), key=lambda p: (not p.name.startswith("_"), p.name)
    )
    for i, item in enumerate(top_items):
        is_last_top = i == len(top_items) - 1
        connector = "└── " if is_last_top else "├── "
        annotation = _annotate(item.name)
        suffix = f"  {annotation}" if annotation else ""
        lines.append(f"{connector}{item.name}{suffix}")
        if item.is_dir():
            sub_items = sorted(
                item.iterdir(), key=lambda p: (not p.name.startswith("_"), p.name)
            )
            for j, sub in enumerate(sub_items):
                is_last_sub = j == len(sub_items) - 1
                sub_connector = "    └── " if is_last_sub else "    ├── "
                if not is_last_top:
                    sub_connector = "│   " + sub_connector[4:]
                lines.append(f"{sub_connector}{sub.name}")

    lines.append("")
    lines.append(
        "Legend:\n  [auto]   — managed by server, never edit directly\n"
        "  [human]  — scaffolded by server, edit freely\n"
        "  [append] — append-only, use append_to_file tool"
    )
    return "\n".join(lines)


def _section_tool_inventory(mcp: "fastmcp.FastMCP") -> str:
    """Build the tool inventory from registered tools at call time."""
    try:
        tools = asyncio.run(mcp.list_tools())
    except RuntimeError:
        # Already inside an event loop — use a thread pool executor approach
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            tools = pool.submit(asyncio.run, mcp.list_tools()).result()

    fs_lines: list[str] = []
    global_lines: list[str] = []

    for tool in sorted(tools, key=lambda t: t.name):
        sig = inspect.signature(tool.fn)
        param_parts: list[str] = []
        for pname, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty:
                param_parts.append(f"**{pname}**")
            else:
                param_parts.append(pname)
        params_str = " ".join(param_parts) if param_parts else "—"
        # Truncate description to one sentence
        desc = (tool.description or "").split("\n")[0].rstrip(".")
        line = f"  {tool.name:<32} {params_str:<35} {desc}."
        if tool.name in _GLOBAL_ENTITY_TOOLS:
            global_lines.append(line)
        else:
            fs_lines.append(line)

    sections: list[str] = ["## Tool inventory", ""]
    if fs_lines:
        sections.append("### Filesystem tools")
        sections.append("")
        sections.extend(fs_lines)
        sections.append("")
    if global_lines:
        sections.append("### Global entity tools")
        sections.append("")
        sections.extend(global_lines)
        sections.append("")
    return "\n".join(sections).rstrip()


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def generate_guide(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Generate the full server guide as a UTF-8 markdown string.

    Never raises — wraps all errors and returns a fallback string so the LLM
    always gets something useful.
    """
    try:
        sections = [
            _section_header(root),
            _SECTION_WHAT_THIS_MANAGES,
            _section_root_structure(root),
            _SECTION_PROJECT_LAYOUT,
            _section_tool_inventory(mcp),
            _SECTION_REF_SYNTAX,
            _SECTION_KEY_SCHEMAS,
            _SECTION_FS_RULES,
            _SECTION_FOOTER,
        ]
        return "\n\n".join(sections)
    except Exception as exc:  # pragma: no cover
        return (
            f"# Project Memory MCP — Server Guide\n\n"
            f"_Error generating guide: {exc}_\n\n"
            f"Use list_projects to see available projects."
        )
