# Quick Reference — Tokens, Rules, and Parameters

This is the single source of truth for reference syntax, filesystem rules, and tool parameters.
For full context and examples, see [guide.md](guide.md) and [m365-guide.md](m365-guide.md).

## Reference token syntax

Use these tokens in Markdown bodies, frontmatter, or any text field.
All tokens are parsed and indexed on every write.

| Token | Resolves to |
|---|---|
| `@person-slug` | `_global/people/{slug}.md` |
| `@company-slug` | `_global/companies/{slug}.md` |
| `#tag` | canonical tag list in `_global/tags.md` |
| `[[project-slug]]` | `projects/{slug}/` folder |
| `[mem:projects/proj/notes/x.md]` | internal workspace cross-reference |
| `[sp:source-id/path]` | SharePoint document (requires registered source) |
| `[tm:source-id/message-id]` | Teams message (requires registered source) |
| `[ol:source-id/message-id]` | Outlook email (requires registered source) |

**Notes:**
- `source-id` is the `id` field from `_sync.yaml` sources, not raw M365 IDs
- **All M365 tokens require source registration via `add_sync_source` first**
- Unresolved `@refs` and `[mem:]` refs produce warnings (file still written)
- Multiple sources in `knowledge/` frontmatter:
  ```yaml
  source:
    - "[sp:sp-contracts/msa-v2.pdf]"
    - "[mem:projects/acme/correspondence/q1-thread.md]"
  ```

## Filesystem rules — severity matrix

| Rule | Details | Severity |
|---|---|---|
| Path inside memory root | All file paths must stay within memory-root | Error |
| Filenames kebab-case | `email-threads.md` ✓  `Email Threads.md` ✗ | Error |
| Project slugs unique | No two projects can share the same slug | Error |
| Dates YYYY-MM-DD | All date fields must parse as valid dates | Error |
| `_index.yaml` read-only | Cannot read or write manifest directly | Error |
| `projects/*/people.md` auto-managed | Never edit directly; use link/unlink tools | Error |
| `updates/` and `decisions.md` append-only | Use `append_to_file`, never `write_file` | Error |
| Knowledge entries need frontmatter | Every `knowledge/*.md` requires `source`, `processed`, `method` | Warning |
| Unresolved `@ref` tokens | References to non-existent people/companies/projects | Warning |
| Unresolved `[mem:path]` tokens | References to non-existent workspace files | Warning |

## Project memory as source of truth — the principle

**Once knowledge is processed and stored in the project memory filesystem, treat it as your
primary source.** This principle saves tokens and reduces latency.

### Local-first decision tree

| Scenario | Action |
|---|---|
| Knowledge entry exists in `knowledge/`, `correspondence/`, or `updates/` | **Read locally first** — use the stored summary, don't re-fetch |
| Entry has `source: [sp:...]` / `[tm:...]` / `[ol:...]` frontmatter | **Entry is canonical** — metadata documents what was processed and when |
| Entry marked `stale_after: YYYY-MM-DD` and date has passed | **Optional re-fetch** — only if user asks for updates or compliance audit required |
| Source is newly registered, never processed before | **Fetch once** — process and store with proper frontmatter |
| User explicitly asks "What's changed?" or "Pull fresh data" | **Re-fetch that source** — but cache result again to avoid repeating in same session |
| Validating against live source for compliance/audit | **Re-fetch** — rare case; update story with findings |

### Why prioritize local memory

- **Processed summaries are cheaper** — A 50-page contract summary costs less to load from disk than re-fetching from SharePoint
- **Metadata tells the story** — `source:`, `processed:`, `method:` fields document exactly what was done and when
- **Avoids redundant M365 calls** — SharePoint quotas and Teams limits mean re-fetching the same content wastes quota
- **Token efficiency** — Stored Markdown is compressed vs. re-reading full source documents

### Citation pattern

When referencing processed knowledge, always include the local source link:

```
According to our processed notes (from [sp:sp-contracts/msa-v2.pdf]),
the contract term is 24 months.
```

This maintains auditability, signals that data is processed (not raw), and reduces stale-data risk.

## Common tool parameters

### project_slug
Used in: `get_project_context`, `create_project`, `add_sync_source`, etc.
- kebab-case identifier (e.g., `acme-platform`)
- Must be globally unique
- Verified via `list_projects` before creation

### source_type
Used in: `add_sync_source`, `update_sync_state`
- Valid values: `teams`, `outlook`, `sharepoint`
- Determines which M365 service and what metadata fields apply

### folder_path
Used in: `get_folder_manifest`, `update_manifest`, `update_file_description`
- Path like `projects/acme-platform/correspondence`
- Target must exist before calling these tools

### path
Used in: `read_file`, `write_file`, `append_to_file`, `delete_file`, `get_related_files`
- Must be relative to memory-root
- Examples: `projects/slug/_status.md`, `_global/people/alice-manager.md`
- Cannot escape memory-root (detected as error)

### slug (person or company)
Used in: `create_person`, `create_company`, `get_person`, `get_company`, etc.
- kebab-case identifier (e.g., `alice-manager`)
- Must be globally unique within people or companies
- Verify via `list_global_people` / `list_global_companies` before creation

### company (person creation)
Used in: `create_person`
- Required parameter
- Value: a company slug like `@acme-corp` or string `"Other"`
- Warns if set to `"Other"` (company genuinely unknown)

## Knowledge entry frontmatter (required)

Every file under `projects/{slug}/knowledge/` must include:

```yaml
source: str | [str] | null   # M365 ref, [mem:] path, text description, or list of sources
processed: YYYY-MM-DD        # When this entry was created/updated
method: manual | summary | extract  # How it was processed (manual notes, LLM summary, or extraction)
model: str                   # (optional) Which LLM model if applicable
prompt_ref: str              # (optional) Reference to the prompt used
stale_after: YYYY-MM-DD      # (optional) When to consider this entry outdated
```

Example valid frontmatter:
```yaml
source: "[sp:sp-contracts/msa-v2.pdf]"
processed: 2026-03-28
method: summary
model: claude-opus
```

## Quick navigation

- **For deep context on local-first principle:** See "Project memory as source of truth" in [guide.md](guide.md#project-memory-as-source-of-truth)
- **For M365 sync pipeline details:** See [m365-guide.md](m365-guide.md)
- **For complete tool inventory:** See "Tool inventory" in [guide.md](guide.md#tool-inventory)
- **For JSON schemas (\_meta.yaml, \_index.yaml, \_sync.yaml):** See "Key schemas" in [guide.md](guide.md#key-schemas)
- **For folder routing decisions:** See "Folder routing rules" in [guide.md](guide.md#folder-routing-rules)
- **For new project setup:** See [creating-new-project.md](creating-new-project.md)
