"""Template strings for all memory-root file types."""

PROJECT_GUIDE_TEMPLATE = """\
# Project Folder Guide

This folder contains structured memory for this project. Below is a quick reference
for what each file and sub-folder contains and when to read it.

| Folder / File | Contains | Read when |
|---|---|---|
| `_status.md` | Always-current project status, next action, blockers | First — before loading any other context for this project |
| `_meta.yaml` | Project metadata (status, type, owner, tags) | When filtering or understanding project scope |
| `_index.yaml` | Auto-managed manifest of all files (descriptions + read-when) | Use `get_folder_manifest` tool |
| `people.md` | Key contacts and stakeholders on this project | Before any communication or meeting |
| `companies.md` | Company relationships relevant to this project | When researching company context |
| `decisions.md` | Architecture and key decisions log (append-only) | Before making decisions that may overlap |
| `knowledge/` | Processed knowledge entries (source material, summaries) | When researching a topic |
| `correspondence/` | Email threads, calls, messages | When reviewing communication history |
| `updates/` | Chronological date-stamped update log (append-only) | For recent progress and status |
| `docs/` | Reference documents and specs | When working with external documents |
| `notes/` | Free-form notes | For general reference |

> **Note:** Never edit `_index.yaml` directly. Use the `update_file_description` tool.
> `_status.md` and `_guide.md` are human-editable and not auto-managed.
"""

PROJECT_STATUS_TEMPLATE = """\
# Status — {name}

> As of {date}: _(no status set yet — update this after every key event)_

**Current state:** 
**Next action:** 
**Blocked on:** 
**Last updated:** {date}
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
**Company:** Other
**Email:** 
**Phone:** 
**Description:** 

## Notes
_(manual notes empty)_

## Projects
- (none)

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

UPDATES_MANIFEST_TEMPLATE = """\
# Auto-managed by the MCP server. This folder is a chronological append-only log.
last_updated: "{date}"
stale: false
description: "Chronological update log. Read the file directly for recent entries."
last_entry_date: null
files: []
"""

ROOT_MANIFEST_TEMPLATE = """\
# Auto-managed by the MCP server. Lists all projects.
last_updated: "{date}"
projects: []
"""

SYNC_YAML_TEMPLATE = """\
# Auto-managed by sync pipeline. Do not edit manually.
# Missing file = no M365 sources configured for this project. Not an error.

last_sync: null

sources:
  teams: []
  outlook: []
  sharepoint: []

pipeline:
  correspondence_frequency: daily
  knowledge_frequency: weekly
  last_knowledge_synthesis: null
  next_knowledge_synthesis: null
"""
