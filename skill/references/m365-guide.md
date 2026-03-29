# Project Memory — M365 Integration Guide
_Generated: 2026-03-29_

## M365 availability model
The memory MCP server **never calls M365 directly**.
M365 data enters the memory filesystem via:
1. The sync pipeline script (automated — reads M365 MCP, writes via memory MCP)
2. Manual fetch (call M365 MCP yourself, save result via `write_file` or `create_knowledge_entry`)

All memory MCP tools work without M365 connectivity.
`resolve_m365_ref` returns local metadata only — it does **not** fetch live data.

## Using local processed data as source of truth

See the full **local-first decision tree** in [`quick-reference.md`](quick-reference.md#project-memory-as-source-of-truth--the-principle).

Inline summary:
- **Primary principle:** Once M365 content is processed and stored in project memory,
  treat the local summary as your primary source — saves tokens, reduces latency
- **When to use local:** Knowledge exists in `knowledge/`, `correspondence/`, `updates/` with `source:` frontmatter
- **When to fetch fresh:** Only if `stale_after:` date passed, user asks for updates, source is new, or audit required
- **Citation pattern:** "According to our processed notes (from [sp:sp-contracts/msa-v2.pdf]), ..."

## M365 reference syntax

See the complete token table in [`quick-reference.md`](quick-reference.md#reference-token-syntax).

**Critical reminder:**
- `source-id` is the `id` field from `_sync.yaml` sources — **not** a raw M365 ID
- You must register sources with `add_sync_source` before using their IDs in `[sp:]`, `[tm:]`, `[ol:]` tokens
- Use `get_related_files` to trace bidirectional links for any workspace file

## Source registry
Sources are registered per-project in `_sync.yaml` via `add_sync_source`.
Check registered sources with `get_sync_state`.

## Sync state tools — quick reference

| Tool | Parameters | Description |
|---|---|---|
| `get_sync_state` | project_slug | Read `_sync.yaml`; null result if missing |
| `update_sync_state` | project_slug, source_type, source_id, fields | Merge watermark fields into a source entry |
| `add_sync_source` | project_slug, source_type, id, label, … | Register a new M365 source |
| `list_projects_due_for_sync` | frequency? | Projects with overdue sync sources |
| `list_projects_due_for_synthesis` | — | Projects with overdue knowledge synthesis |
| `resolve_m365_ref` | project_slug, ref | Resolve ref to local metadata |

## _sync.yaml schema

| Field | Type | Notes |
|---|---|---|
| `last_sync` | str\|null | ISO 8601 UTC or null |
| `sources.teams[].id` | str | kebab-case, unique within teams |
| `sources.teams[].label` | str | human-readable |
| `sources.teams[].channel_id` | str | M365 Teams channel ID |
| `sources.teams[].last_processed_at` | str\|null | ISO 8601 UTC watermark |
| `sources.teams[].last_message_id` | str\|null | Teams epoch timestamp watermark |
| `sources.teams[].unprocessed_count` | int | estimated unprocessed messages |
| `sources.teams[].enabled` | bool | false = skipped in pipeline runs |
| `sources.outlook[].folder_id` | str | Outlook folder ID |
| `sources.sharepoint[].site_url` | str | SharePoint site URL |
| `sources.sharepoint[].library` | str | Document library name |
| `sources.sharepoint[].last_modified_etag` | str\|null | ETag watermark |
| `pipeline.correspondence_frequency` | str | `daily` \| `weekly` \| `manual` |
| `pipeline.knowledge_frequency` | str | `daily` \| `weekly` \| `manual` |
| `pipeline.last_knowledge_synthesis` | str\|null | YYYY-MM-DD |
| `pipeline.next_knowledge_synthesis` | str\|null | YYYY-MM-DD (computed on update) |

## Pipeline integration note
The sync pipeline script (Phase 4d, separate from this server) is responsible
for calling M365 MCP tools, summarizing content via Anthropic API, and writing
results back via memory MCP tools. The memory server is stateless with respect
to M365 — it stores watermarks and references but never initiates M365 calls.

## Manual M365 → memory workflow
When saving M365 content manually (without the sync pipeline):

1. Fetch content using M365 MCP tools (`sharepoint_search`, `read_resource`, `outlook_email_search`, `chat_message_search`, etc.)
2. Summarize or extract the relevant information
3. Register the source if not already registered: `add_sync_source`
4. Save to the correct folder using the routing table (e.g. `correspondence/email-threads.md` for email summaries)
5. Use M365 reference tokens in the body/frontmatter to link back to the original source
6. Update the watermark: `update_sync_state`
