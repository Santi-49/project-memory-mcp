---
name: project-memory-mcp
description: >
  Use this skill whenever you are about to use ANY tool from the project-memory-mcp
  server — including create_project, create_person, create_knowledge_entry, write_file,
  get_project_context, read_file, append_to_file, add_sync_source, or any other
  project-memory-mcp tool. This skill MUST be loaded before the first project-memory-mcp
  call in every conversation. It provides the server guide and the M365 integration
  guide that are required reading before operating on the memory filesystem.
  Trigger on any user request that involves saving project info, creating project memory,
  updating people/companies, logging knowledge, syncing from M365 sources (SharePoint,
  Teams, Outlook), or querying the project memory MCP.
---

# Project Memory MCP — Required Pre-Flight

Before calling any `project-memory-mcp` tool, read both reference files in this skill.
They are short but critical — skipping them causes structural mistakes that are hard
to undo (wrong folder routing, missing frontmatter, broken @ref tokens, unregistered
M365 sources).

## Step 1 — Quick reference, then read the server guide

First, review [`references/quick-reference.md`](references/quick-reference.md) for:

- Reference token syntax (single canonical table)
- Filesystem rules severity matrix
- Project memory as source of truth (local-first decision tree)

Then read [`references/guide.md`](references/guide.md) for:

- Root and project folder layout (where things live)
- **Folder routing rules** — which folder to use for each type of content
- Full tool inventory with required parameters
- Key schemas for `_meta.yaml`, `knowledge/` frontmatter, `_index.yaml`

## Step 2 — Read the M365 integration guide

Read [`references/m365-guide.md`](references/m365-guide.md) now.

It covers:

- How M365 data enters the memory filesystem (sync pipeline vs. manual fetch)
- **Using local processed data as source of truth** — token efficiency principle
- M365 reference token syntax with examples
- `_sync.yaml` schema (sources, watermarks, pipeline frequencies)
- `add_sync_source` / `update_sync_state` usage
- `resolve_m365_ref` scope and limitations

## Step 3 — Key rules to keep in mind

These are the most commonly violated rules — worth internalising before you start:

1. **Read before mutating.** Always call `get_person`, `get_company`, `get_project_context`,
   or `read_file` before any update. Overwriting newer content is hard to recover from.

2. **Check for duplicates first.** Before `create_person` or `create_company`, call
   `list_global_people` / `list_global_companies` to avoid duplicate entries.

3. **Use the routing table.** Don't put everything in `knowledge/`. Use
   `correspondence/` for email/call/chat summaries, `updates/` for the chronological
   log, `notes/` for drafts. See the routing table in `references/guide.md`.

4. **Know the filesystem rules.** See the severity matrix in `references/quick-reference.md`.
   Key constraints: kebab-case filenames, append-only `updates/` and `decisions.md`,
   auto-managed `people.md` and `companies.md`, YAML frontmatter required in `knowledge/`.

5. **Project memory is source of truth.** See the local-first decision tree in
   `references/quick-reference.md`. Once knowledge is processed and stored, use the
   local summary as your primary source. Avoid re-fetching the same M365 content
   multiple times — it wastes tokens.

## Step 4 — If you're creating a new project

If the user is asking you to **initialize or set up a new project**, read [`references/creating-new-project.md`](references/creating-new-project.md) first.

It provides:

- Pre-flight constraints (5 things to check before starting)
- 12-step walkthroughs for complete project initialization
- Templates for `_status.md`, `decisions.md`, and `_guide.md`
- Common mistakes and how to avoid them
- Quick verification checklist

This guide ensures your project is properly structured and will follow all the routing
rules and schemas from Steps 1-3.

---

Once you've read the relevant reference files above, proceed with the user's request
using the appropriate tools.
