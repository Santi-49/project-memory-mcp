# Indexable Files

All markdown files in the Project Memory MCP filesystem are automatically indexed for semantic search and discovery. This document describes what files are indexable and how to ensure optimal indexability.

---

## Overview

> Every markdown file (`.md`) in the memory-root filesystem is **automatically indexed** via TF-IDF (or embeddings-based) search. Only `_index.yaml` and configuration files are excluded.

The RAG (Retrieval-Augmented Generation) system:
- Indexes new files when they are written
- Re-indexes files when they are modified  
- Detects modified files by comparing modification time (`mtime`)
- Stores term frequencies and metadata for fast semantic queries
- Supports both TF-IDF and embedding-based backends

---

## Indexable directories

### `_global/people/`

All `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `*.md` (person profiles) | Team member profiles with role, company, email, notes | ✅ Yes |
| `_index.yaml` | Manifest of people files | ❌ No |

**Example:** `_global/people/alice-smith.md`
```yaml
---
name: Alice Smith
title: Data Engineer
company: BlueTAB
email: asmith@bluetab.com
other:
  phone: +34 XXX XXX XXX
---

# Alice Smith

Data engineer specializing in Snowflake migrations...
```

**Optimal for:** Finding team members by role, company, or expertise.

---

### `_global/companies/`

All `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `*.md` (company profiles) | Partner, client, or internal company information | ✅ Yes |
| `_index.yaml` | Manifest of company files | ❌ No |

**Optimal for:** Understanding company context, partnerships, and organizational structure.

---

### `projects/{slug}/knowledge/`

All `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `*.md` (knowledge entries) | Processed knowledge derived from M365 sources or manual entry | ✅ Yes |
| `_index.yaml` | Manifest with file descriptions and `read_when` hints | ❌ No |

Each knowledge file **must** start with YAML frontmatter:

```markdown
---
source: "[sp:sp-contracts/architecture.pdf]"  # or [tm:teams-msg] or [ol:outlook-thread]
processed: "2026-03-29"
method: "extract"  # or "summary", "synthesis"
model: "claude-sonnet-4-6"
---

# Architecture Overview

...
```

**Optimal for:** Capturing processed insights, summaries, and technical documentation.

---

### `projects/{slug}/correspondence/`

All `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `email-threads.md` | Summaries of Outlook email threads with dates and action items | ✅ Yes |
| `calls.md` | Call and meeting notes with participants and decisions | ✅ Yes |
| `messages.md` | Teams/Slack message summaries | ✅ Yes |
| `_index.yaml` | Manifest | ❌ No |

**Optimal for:** Finding communication history, agreements, and verbal decisions.

---

### `projects/{slug}/updates/`

All `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `YYYY-MM.md` (monthly logs) | Chronological project updates, entry per date (append-only) | ✅ Yes |
| `_index.yaml` | Manifest | ❌ No |

Format:

```markdown
# Updates — ProjectName — YYYY-MM

## YYYY-MM-DD — Event Title
**Participants:** ...
**Decisions:** ...
**Action items:** ...

---

## YYYY-MM-DD — Another Event
...
```

**Optimal for:** Tracking project progress chronologically.

---

### `projects/{slug}/decisions.md`

Single file, **indexed**.

| File | Content | Indexable |
|---|---|---|
| `decisions.md` | Append-only decision log with rationale and context | ✅ Yes |

Format:

```markdown
# Decisions — ProjectName

## [YYYY-MM-DD] Use Snowflake for data warehouse

**Rationale:** Cost-effective, integrates with dbt, native Iceberg support.
**Context:** Reviewed 3 alternatives (AWS Redshift, BigQuery, Snowflake).
**Owner:** @alice-smith
**Status:** Decided

---

## [YYYY-MM-DD] Another decision
...
```

**Optimal for:** Understanding project direction and trade-offs.

---

### `projects/{slug}/docs/`

When populated, all `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `*.md` (project documents) | Specifications, working documents, external references | ✅ Yes |
| `_index.yaml` | Manifest | ❌ No |

**Optimal for:** Storing project specs, component designs, or working notes.

---

### `projects/{slug}/notes/`

When populated, all `.md` files are **indexed**.

| File | Content | Indexable |
|---|---|---|
| `*.md` (free-form notes) | Drafts, brainstorms, unstructured observations | ✅ Yes |
| `_index.yaml` | Manifest | ❌ No |

> **Note:** Files here are indexed but typically less polished. Use `knowledge/`, `correspondence/`, or `updates/` for final/processed content.

**Optimal for:** Storing rough ideas before refining into knowledge entries.

---

### Project-level metadata

| File | Content | Indexable |
|---|---|---|
| `_status.md` | Current blockers, wins, and next actions | ✅ Yes |
| `decisions.md` | Append-only decision log | ✅ Yes |
| `people.md` | Auto-managed list of team members | ✅ Yes |
| `companies.md` | Auto-managed list of relevant companies | ✅ Yes |
| `_meta.yaml` | Project metadata (slug, status, tags) | ❌ No |
| `_index.yaml` | Manifest | ❌ No |

---

## Non-indexable files

These files are **never indexed**:

| File | Why |
|---|---|
| `_index.yaml` | Auto-managed manifest (contains routing, not content) |
| `_meta.yaml` | Metadata (filtering key, not searchable) |
| `_sync.yaml` | Sync configuration (technical, not content) |
| `_trash/*` | Soft-deleted files |
| `_templates/*` | Template scaffolds (not project content) |
| `_guide.md` | Project guide (auto-managed) |
| Any `.*` (dotfiles) | Hidden files |

---

## Ensuring optimal indexability

### 1. Use clear, descriptive filenames

✅ **Good:**
- `architecture-and-design.md`
- `2026-03-deployment-requirements.md`
- `okta-federation-setup.md`

❌ **Poor:**
- `notes.md`
- `doc1.md`
- `tmp.md`

Filenames should reflect content and be **kebab-case** (lowercase, hyphens).

### 2. Add descriptions to `_index.yaml`

Edit the `_index.yaml` manifest in each folder to add human-readable descriptions:

```yaml
files:
- name: architecture.md
  description: AWS infrastructure design for DataBuddy (EKS, Bedrock, RDS, networking)
  read_when: Before making infrastructure decisions
  stale_after: 7 days  # Suggest re-read interval
```

### 3. Write semantically rich content

Use domain-specific terms and context:

✅ **Good:**
```markdown
# Snowflake Migration Strategy

The project uses **dbt** (data build tool) to manage transformations.
Schema: `staging_sales` → `marts_sales`. 

Key entities:
- Orders: grain = order_id
- Line Items: grain = order_item_id
```

❌ **Poor:**
```markdown
# Notes

We are moving data to Snowflake. It uses SQL. Lots of tables.
```

### 4. Include source references (for knowledge entries)

Always include frontmatter in `knowledge/` files:

```yaml
---
source: "[sp:sp-contracts/requirements.pdf]"
processed: "2026-03-29"
method: "extract"
model: "claude-sonnet-4-6"
---
```

This helps LLMs track lineage and avoid re-fetching M365 sources.

### 5. Keep files focused

Each file should address **one main topic**:

✅ **Good structure:** One file per:
- Team member profile
- Company overview
- Technical decision
- Monthly update
- Meeting summary

❌ **Poor structure:** One file with everything mixed together.

### 6. Update modification dates

Files are detected as "modified" by comparing `mtime` (modification time) against last indexed time. To force re-indexing:

```bash
# Touch the file to update mtime
touch c:/path/to/file.md
```

---

## Index metadata

The RAG index stores:

```json
{
  "_rag_index.json": {
    "version": 1,
    "docs": {
      "path/to/file.md": {
        "tf": { "term1": freq, "term2": freq, ... },
        "mtime": 1774796858.3323283,
        "indexed_at": "2026-03-29T18:49:17.855188+00:00"
      }
    },
    "idf": { "term1": score, "term2": score, ... }
  }
}
```

- **tf:** Term frequency (count / total tokens in file)
- **mtime:** File modification time (Unix timestamp)
- **indexed_at:** When the file was indexed
- **idf:** Inverse document frequency (global importance of each term)

---

## Querying indexed files

Use the RAG system to search:

1. **TF-IDF search** (keyword + semantic) — Fast, no dependencies
2. **Embedding search** (semantic only) — Requires `sentence-transformers`

Both backends expose the same interface. See [`src/rag.py`](../src/rag.py) for implementation details.

---

## Summary checklist

Before considering a file "indexable" and discoverable:

- [ ] File is in an indexable directory (`people/`, `knowledge/`, `correspondence/`, etc.)
- [ ] Filename is descriptive and kebab-case
- [ ] File has a description in `_index.yaml` (or auto-managed)
- [ ] Content is human-readable and focused on one topic
- [ ] If in `knowledge/`, includes YAML frontmatter with source reference
- [ ] File follows the appropriate schema (e.g., person, knowledge entry, decision, update)
- [ ] `_index.yaml` is not manually edited (let the MCP server manage it)

---

## Related docs

- [`README.md`](../README.md) — Overview and quick start
- [`filesystem-rules.md`](./filesystem-rules.md) — Enforcement rules and constraints
- [`memory-root-schema.md`](./memory-root-schema.md) — File/folder schema definitions
- [`tool-reference.md`](./tool-reference.md) — MCP tool reference
