# Default Templates — Reference

This directory contains templates for all **human-editable** files in the project memory filesystem.
These templates are automatically populated with context-specific values when creating
new projects, people, companies, and knowledge entries.

**Note:** Auto-managed templates (manifests, sync configuration) are not included here —
they are generated and updated by the server tools and should never be edited directly.

## Project Templates

**When creating a project** (`create_project`), the server scaffolds:
- [project-status.md](project-status.md) — Initial project status (editable)
- [project-instructions.md](project-instructions.md) — Custom LLM behavior rules (editable)
- [project-guide.md](project-guide.md) — Folder structure reference (editable)
- [project-meta.yaml](project-meta.yaml) — Project metadata structure (editable)

## Global Entity Templates

**When creating a person** (`create_person`):
- [person.md](person.md) — Person profile with title, company, contact info (editable)

**When creating a company** (`create_company`):
- [company.md](company.md) — Company profile with industry, website, contacts (editable)

## Knowledge & Content Templates

**For knowledge entries** (`create_knowledge_entry`):
- [knowledge-entry.md](knowledge-entry.md) — Knowledge entry with YAML frontmatter (editable)

**For meeting summaries** (manual template):
- [meeting-note.md](meeting-note.md) — Call/meeting summary template (editable)

## Customizing Templates

To customize templates for your use case:
- Edit these files directly (they are just examples)
- The server will use the customized versions for future scaffolding
- Or pass custom content to `create_project`, `create_person`, etc. tools via parameters
