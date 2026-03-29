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
| `correspondence/email-threads.md` | Email summaries and thread outcomes | When tracking approvals, commitments, or async decisions |
| `correspondence/calls.md` | Meeting and call summaries | When reconstructing discussions and verbal agreements |
| `correspondence/messages.md` | Chat/IM summaries (Teams/Slack) | When checking fast-moving blockers and ad-hoc decisions |
| `updates/` | Chronological date-stamped update log (append-only) | For recent progress and status |
| `docs/` | Reference documents and specs | When working with external documents |
| `notes/` | Free-form notes | For general reference |

> **Note:** Never edit `_index.yaml` directly. Use the `update_file_description` tool.
> `_status.md` and `_guide.md` are human-editable and not auto-managed.
>
> **Routing quick rules:**
> Put stable, reusable knowledge in `knowledge/`; put timeline events in `updates/`; put irreversible choices in `decisions.md`; put source communication in `correspondence/*`; put working drafts in `notes/`.
