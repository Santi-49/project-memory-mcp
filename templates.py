"""Template strings for all memory-root file types."""

PROJECT_GUIDE_TEMPLATE = """\
# Project Folder Guide

This folder contains structured memory for this project. Below is a quick reference
for what each file and sub-folder contains and when to read it.

| File / Folder | Description | Read when |
|---|---|---|
| `_meta.yaml` | Project metadata (status, type, owner, tags) | Always read first for context |
| `_index.yaml` | Auto-managed manifest of all files (descriptions + read-when) | Use `get_folder_manifest` tool |
| `people.md` | Key contacts and stakeholders on this project | Before any communication or meeting |
| `companies.md` | Company relationships relevant to this project | When researching company context |
| `decisions.md` | Architecture and key decisions log (append-only) | Before making decisions that may overlap |
| `knowledge/` | Processed knowledge entries (source material, summaries) | When researching a topic |
| `correspondence/` | Email threads, calls, messages | When reviewing communication history |
| `updates/` | Date-stamped project updates (append-only) | For recent progress and status |
| `docs/` | Reference documents and specs | When working with external documents |
| `notes/` | Free-form notes | For general reference |

> **Note:** Never edit `_index.yaml` directly. Use the `update_file_description` tool.
> The `_guide.md` file (this file) is human-editable and not auto-managed.
"""

PROJECT_META_TEMPLATE = """\
# Project metadata — auto-populated by create_project, human-editable thereafter.
id: "{id}"
slug: "{slug}"
name: "{name}"
status: "{status}"
type: "{type}"
company: null        # @company-slug
owner: null          # @person-slug
team: []             # list of @person-slugs
tags: []
created: "{created}"
updated: "{updated}"
"""

PERSON_TEMPLATE = """\
# {name}

**Title:** 
**Company:** 
**Email:** 
**Phone:** 

## Notes

## Projects

## Interactions

"""

COMPANY_TEMPLATE = """\
# {name}

**Industry:** 
**Website:** 
**Description:** 

## Key Contacts

## Projects

## Notes

"""

KNOWLEDGE_ENTRY_TEMPLATE = """\
---
source: null
processed: null
method: null
model: null
prompt_ref: null
---

# {topic}

## Summary

## Key Points

## Raw Notes

"""

MEETING_NOTE_TEMPLATE = """\
# Meeting — {date}

**Date:** {date}
**Attendees:** 
**Location / Call:** 

## Agenda

1. 

## Notes

## Decisions

## Action Items

- [ ] 

"""

EMPTY_MANIFEST = """\
# Auto-managed by the MCP server. Edit descriptions via update_file_description tool.
last_updated: "{date}"
stale: false
files: []
"""

ROOT_MANIFEST_TEMPLATE = """\
# Auto-managed by the MCP server. Lists all projects.
last_updated: "{date}"
projects: []
"""
