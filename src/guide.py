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

Use these tokens anywhere in Markdown file bodies or frontmatter fields.
Parsed and indexed by the server on every write.

  @person-slug                     → resolves to _global/people/{slug}.md
  @company-slug                    → resolves to _global/companies/{slug}.md
  #tag                             → canonical list in _global/tags.md
  [[project-slug]]                 → resolves to projects/{slug}/
  [mem:projects/proj/notes/x.md]  → internal cross-reference to another workspace file
  [sp:source-id/path]             → SharePoint document (registered in _sync.yaml)
  [tm:source-id/message-id]       → Teams message (registered in _sync.yaml)
  [ol:source-id/message-id]       → Outlook email (registered in _sync.yaml)

Unresolved @refs and unresolved [mem:] refs produce warnings, not errors.
File is still written — warnings are returned in the tool response.
Use get_related_files to trace bidirectional links between workspace files.

knowledge/ entries may list multiple sources in frontmatter:
  source: "[sp:sp-contracts/msa-v2.pdf]"        # single source
  source:                                         # multiple sources
    - "[sp:sp-contracts/msa-v2.pdf]"
    - "[mem:projects/acme/correspondence/q1-thread.md]" """

_SECTION_KEY_SCHEMAS = """\
## Key schemas

### _meta.yaml
id, slug, name, status (active|paused|completed|archived),
type (client|internal|research|personal), company (@slug),
owner (@slug), team ([@slug]), tags ([str]), created, updated

### knowledge/ frontmatter (required on every knowledge entry)
source: str | [str] | null  — M365 ref, [mem:] path, plain text, or list of these
processed (YYYY-MM-DD), method (manual|summary|extract),
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
Unresolved [mem:path] tokens            write_file, append_to_file      Warning
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


# ---------------------------------------------------------------------------
# M365 guide — static section constants
# ---------------------------------------------------------------------------

_M365_SECTION_AVAILABILITY = """\
## M365 availability model

The memory MCP server never calls M365 directly.
M365 data enters the memory filesystem via:
  1. The sync pipeline script (automated, reads M365 MCP, writes via memory MCP)
  2. Manual fetch (call M365 MCP yourself, save result via write_file or
     create_knowledge_entry)

All memory MCP tools work without M365 connectivity.
resolve_m365_ref returns local metadata only — it does not fetch live data."""

_M365_SECTION_REF_SYNTAX = """\
## M365 reference syntax

Use these tokens in Markdown file bodies or frontmatter to link content to M365 sources
or to other internal workspace files.  All tokens are parsed and indexed on every write.

  [tm:source-id]                   Teams channel reference
  [tm:source-id/message-id]        Specific Teams message
  [ol:source-id]                   Outlook folder/thread reference
  [ol:source-id/message-id]        Specific email message
  [sp:source-id]                   SharePoint library root
  [sp:source-id/path/to/file.pdf]  Specific SharePoint file
  [mem:projects/proj/notes/x.md]   Internal cross-reference to another workspace file

source-id (for M365 tokens) is the id field from _sync.yaml sources, not a raw M365 ID.

### Examples

In a knowledge entry body:
  This contract was reviewed in [sp:sp-contracts/msa-v2.pdf].
  Related background in [mem:projects/acme/knowledge/legal-context.md].

In correspondence:
  Thread summary pulled from [ol:outlook-internal/AAMkAGI2...].

In decisions.md:
  Architecture decision confirmed on call [tm:teams-general/123456789]

knowledge/ frontmatter — multiple sources:
  source:
    - "[sp:sp-contracts/msa-v2.pdf]"
    - "[mem:projects/acme/correspondence/q1-thread.md]"

Use get_related_files to trace bidirectional links for any workspace file."""

_M365_SECTION_SYNC_TOOLS = """\
## Sync state tools — quick reference

  Tool                             Parameters                              Description
  ──────────────────────────────── ─────────────────────────────────────── ────────────────────────────────────────────
  get_sync_state                   project_slug                            Read _sync.yaml; null result if missing.
  update_sync_state                project_slug source_type source_id      Merge watermark fields into a source entry.
                                   fields
  add_sync_source                  project_slug source_type id label ...   Register a new M365 source.
  list_projects_due_for_sync       frequency?                              Projects with overdue sync sources.
  list_projects_due_for_synthesis  —                                       Projects with overdue knowledge synthesis.
  resolve_m365_ref                 project_slug ref                        Resolve ref to local metadata."""

_M365_SECTION_SCHEMA = """\
## _sync.yaml schema

Field                              Type      Notes
────────────────────────────────── ───────── ─────────────────────────────────────
last_sync                          str|null  ISO 8601 UTC or null
sources.teams[].id                 str       kebab-case, unique within teams
sources.teams[].label              str       human-readable
sources.teams[].channel_id         str       M365 Teams channel ID
sources.teams[].last_processed_at  str|null  ISO 8601 UTC watermark
sources.teams[].last_message_id    str|null  Teams epoch timestamp watermark
sources.teams[].unprocessed_count  int       estimated unprocessed messages
sources.teams[].enabled            bool      false = skipped in pipeline runs
sources.outlook[].folder_id        str       Outlook folder ID
sources.sharepoint[].site_url      str       SharePoint site URL
sources.sharepoint[].library       str       Document library name
sources.sharepoint[].last_modified_etag  str|null  ETag watermark
pipeline.correspondence_frequency  str       daily | weekly | manual
pipeline.knowledge_frequency       str       daily | weekly | manual
pipeline.last_knowledge_synthesis  str|null  YYYY-MM-DD
pipeline.next_knowledge_synthesis  str|null  YYYY-MM-DD (computed on update)"""

_M365_SECTION_PIPELINE = """\
## Pipeline integration note

The sync pipeline script (Phase 4d, separate from this server) is responsible
for calling M365 MCP tools, summarizing content via Anthropic API, and writing
results back via memory MCP tools. The memory server is stateless with respect
to M365 — it stores watermarks and references but never initiates M365 calls."""


def _m365_section_header() -> str:
    today = date.today().isoformat()
    return f"# Project Memory — M365 Integration Guide\n_Generated: {today}_"


def _m365_section_source_registry(root: Path) -> str:
    """Build a live table of all registered M365 sources across all projects."""
    import yaml as _yaml

    lines = ["## Source registry", ""]
    rows: list[tuple[str, str, str, str, str, str]] = []

    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            slug = project_dir.name
            sync_path = project_dir / "_sync.yaml"
            if not sync_path.exists():
                continue
            try:
                raw = _yaml.safe_load(sync_path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue

            type_map = {"teams": "Teams", "outlook": "Outlook", "sharepoint": "SharePoint"}
            sources_dict = raw.get("sources", {})
            for src_type, src_list in sources_dict.items():
                if not isinstance(src_list, list):
                    continue
                for source in src_list:
                    rows.append((
                        slug,
                        source.get("id", ""),
                        type_map.get(src_type, src_type),
                        source.get("label", ""),
                        source.get("last_processed_at") or "—",
                        "✓" if source.get("enabled", True) else "✗",
                    ))

    if not rows:
        lines.append(
            "| Project | ID | Type | Label | Last processed | Enabled |"
        )
        lines.append("|---|---|---|---|---|---|")
        lines.append("")
        lines.append(
            "_No M365 sources registered. Use add_sync_source to register._"
        )
    else:
        lines.append("| Project | ID | Type | Label | Last processed | Enabled |")
        lines.append("|---|---|---|---|---|---|")
        for slug, sid, stype, label, last, enabled in rows:
            lines.append(f"| {slug} | {sid} | {stype} | {label} | {last} | {enabled} |")

    return "\n".join(lines)


def generate_m365_guide(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Generate the M365 integration guide as a UTF-8 markdown string.

    Never raises — returns a fallback string on error.
    """
    try:
        sections = [
            _m365_section_header(),
            _M365_SECTION_AVAILABILITY,
            _M365_SECTION_REF_SYNTAX,
            _m365_section_source_registry(root),
            _M365_SECTION_SYNC_TOOLS,
            _M365_SECTION_SCHEMA,
            _M365_SECTION_PIPELINE,
        ]
        return "\n\n".join(sections)
    except Exception as exc:  # pragma: no cover
        return (
            f"# Project Memory — M365 Integration Guide\n\n"
            f"_Error generating guide: {exc}_\n\n"
            f"Use get_sync_state to check M365 configuration for a specific project."
        )
