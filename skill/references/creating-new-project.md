# Initializing a New Project — Step-by-Step Guide

Follow this checklist in order when creating a new project memory.
This ensures correct folder structure, metadata, and source registration.

## Pre-flight (read before starting)

Before you create anything, understand these key constraints:

1. **Project slugs are globally unique.** No two projects can have the same slug.
2. **Folder structure is auto-created.** When you call `create_project`, the server
   scaffolds all subdirectories and empty `_index.yaml` files.
3. **Some files are auto-managed.** Never edit `people.md` or `companies.md` directly —
   they are regenerated from global `@person-slug` and `@company-slug` references.
4. **Metadata must be YAML-valid.** Tags, custom fields, and references must parse
   without errors or the tool will reject the input.
5. **M365 sources must be registered first.** Before using `[sp:…]`, `[tm:…]`, or
   `[ol:…]` tokens, call `add_sync_source` and get the returned `id` field.

## Step-by-step initialization

### Step 1 — Verify slug uniqueness

Before creating the project, list existing projects and confirm your chosen slug
is not in use.

1. Call `list_projects` with no filters
2. Scan the returned list for your slug
3. If found, pick a different slug (use kebab-case: `project-name`, not `ProjectName`)
4. If a similar slug exists in archived or paused status, consider reusing/updating that one instead

### Step 2 — Create the project

Call `create_project` with these parameters:

- **slug** (required): Your final kebab-case slug, e.g., `acme-platform`
  - Must be unique (verified in Step 1)
  - Use lowercase letters, hyphens, and numbers only
  - 3-50 characters typically

- **name** (required): Human-readable project name, e.g., `ACME Platform Initiative`
  - This is what will appear in lists and reports
  - Can include spaces and title case

- **type** (optional): Project category — one of:
  - `research` — exploratory, early-stage work
  - `platform` — infrastructure or enabling technology
  - `product` — customer-facing or end-user deliverable
  - `service` — operational or support function
  - `data` — data pipeline or analytics initiative
  - `other` — if none of the above fit

- **status** (optional): Current state — one of:
  - `discovery` — early exploration phase (default for new projects)
  - `active` — actively being worked on
  - `paused` — temporarily halted but not abandoned
  - `completed` — delivered or finished
  - `archived` — historical reference only

- **meta** (optional): Dict with custom fields, e.g.:
  ```python
  meta={
    "owner": "@alice-manager",
    "budget_usd": 250000,
    "go_live": "2026-Q2",
    "domain": "infrastructure"
  }
  ```

The server will auto-create:
- `projects/{slug}/` directory structure
- `projects/{slug}/_meta.yaml` with your metadata
- `projects/{slug}/_instructions.md` with LLM behavior template
- `projects/{slug}/_index.yaml` (empty manifest)
- Subdirectories: `correspondence/`, `docs/`, `knowledge/`, `notes/`, `updates/`

### Step 2b — Set up project instructions (optional)

If you have LLM-specific behavior rules, MCP connector requirements, or project conventions
that should apply to this project, edit `_instructions.md` now.

You should prompt the user if it wants any specific innstructions on MRP ussage or wich of the following options it wants.

**Option A: Start with the template**
1. Call `get_project_context` to retrieve the scaffolded `_instructions.md`
2. Edit each section:
   - **LLM Behavior Rules** — e.g., "Use technical terminology from the domain," "Always cite sources"
   - **MCP Connector Usage** — e.g., "Use [mcp:github/...] for code references", "Use [mcp:jira/...] for issue links"
   - **Project Conventions** — e.g., "File naming: kebab-case", "Decisions require 48h stakeholder review"
3. Call `write_file` with path `projects/{slug}/_instructions.md` and your custom content

**Option B: Copy from another project** (if similar)
1. Call `get_project_context` on the source project slug to retrieve its `_instructions.md`
2. Modify as needed for this new project
3. Call `write_file` with the customized content

You can also leave the default template as-is and update instructions later.

### Step 3 — Edit project metadata

Your new project's metadata is scaffolded but may need refinement.

1. Call `get_project_context` with your slug to see what was created
2. Review the returned `_meta.yaml` content
3. If you need to add/update fields (owner, budget, domain, architectural notes, etc.):
   - Call `update_project` with `meta` dict containing your custom fields
   - Example: `meta={"owner": "@alice-manager", "domain": "infrastructure"}`

### Step 4 — Create the initial status file

Create `_status.md` with current project state and immediate next steps.
This file is loaded first by `get_project_context`, so keep it concise.

1. Call `write_file` with path `projects/{slug}/_status.md`
2. Include:
   - **Current blockers** (what's preventing progress)
   - **Recent wins** (what was accomplished recently)
   - **Immediate next steps** (what needs to happen in the next 1-2 weeks)
   - **Key stakeholders** (people involved or affected)
   - **Key risks** (things that could derail the project)
3. Keep it short: 3-5 paragraphs under 500 words
4. Example template:
   ```
   # Project Status

   ## Current blockers
   - Awaiting AWS account access from ...
   - Need legal review of contract by ...

   ## Recent wins
   - Completed initial architecture review (03-28)
   - DataReady pipeline deployed to staging (03-27)

   ## Immediate next steps
   1. Finalize infrastructure requirements with @alice-manager
   2. Schedule stakeholder kickoff meeting
   3. Create knowledge entries for discovered dependencies

   ## Key stakeholders
   @alice-manager (owner), @bob-lead (tech lead), @charlie-legal (legal)

   ## Key risks
   - M365 sync delays could impact timeline
   - Unclear budget allocation may affect team sizing
   ```

### Step 5 — Create the decisions log

Initialize `decisions.md` as your immutable decision record (append-only).

1. Call `write_file` with path `projects/{slug}/decisions.md`
2. Use this template structure:
   ```
   # Decisions

   This is the irreversible decision log for this project.
   Decisions are appended only (never deleted or reordered).

   ## [YYYY-MM-DD] Decision title
   **Context / Problem:** What situation made this decision necessary?
   **Decision:** What was decided?
   **Rationale:** Why this over alternatives?
   **Alternatives considered:** What else did you evaluate?
   **Timeline:** When was it made? When does it take effect?
   **Owner:** @slug
   ```
3. Add the project establishment decision as the first entry
4. Note: Use `append_to_file` to add decisions later, never `write_file`

### Step 6 — Identify and link key people & companies

Link global people and companies to the project. This auto-updates `people.md`.

1. Call `list_global_people` to see available stakeholders
   - Optional: filter by company with `company="@acme-corp"`
2. Call `list_global_companies` to review registered organizations
3. For each major stakeholder identified:
   - Note their `@slug` (e.g., `@alice-manager`)
   - Call `link_person_to_project` with `person_slug` and `project_slug`
4. Key people to link:
   - **Owner** — who's accountable for the project
   - **Tech lead** — who's driving technical decisions
   - **Domain expert** — who understands the domain deeply
   - **Sponsor** — who's funding or championing this
   - Any other stakeholder mentioned in status or decisions

### Step 7 — Create missing people and companies

If a key stakeholder doesn't exist in the system yet, create them.

1. To create a company:
   - Call `create_company` with:
     - `slug`: kebab-case unique identifier
     - `name`: company display name
     - Optional: `website`, `industry`, `description`

2. To create a person:
   - Call `create_person` with:
     - `slug`: kebab-case unique identifier (typically `firstname-lastname`)
     - `name`: full name
     - `company`: required — use existing company slug or "Other"
     - Optional but encouraged: `title`, `email`, `phone`, `global_description`
   - Example:
     ```python
     create_person(
       slug="jane-developer",
       name="Jane Developer",
       company="@acme-corp",
       title="Senior Software Engineer",
       email="jdeveloper@acme-corp.com",
       phone="+1 555 XXX XXXX",
       global_description="Full-stack engineer with 8+ years in cloud infrastructure"
     )
     ```

3. After creating, link them to the project using Step 6

### Step 8 — Set up correspondence folders

Initialize correspondence with descriptions so they're discoverable.

For each of `email-threads.md`, `calls.md`, `messages.md`:

1. Call `update_file_description` with:
   - `folder_path`: `projects/{slug}/correspondence`
   - `filename`: e.g., `email-threads.md`
   - `description`: Explain what goes here
   - `read_when`: When should the LLM read this?

2. Use these descriptions:

   **email-threads.md:**
   - Description: "Email thread summaries from project sponsors and stakeholders"
   - read_when: "When validating async approvals or tracking commitments"

   **calls.md:**
   - Description: "Meeting and call notes with decisions discussed"
   - read_when: "When reconstructing technical discussions or verbal agreements"

   **messages.md:**
   - Description: "Teams/Slack message summaries covering fast-moving blockers"
   - read_when: "When checking urgent decisions or ad-hoc status updates"

### Step 9 — Create the first update entry

Initialize `updates/` with the project kickoff or current phase.

1. Choose a filename: `{YYYY-MM-DD}-kickoff.md` or `{YYYY}-Q{N}.md`
   - Example: `2026-03-29-kickoff.md` or `2026-Q1.md`

2. Call `write_file` with path `projects/{slug}/updates/{filename}`

3. Include:
   - Project summary (one paragraph)
   - List of events/milestones so far with dates
   - Current phase and expected duration
   - Initial scope/goals

4. Example:
   ```
   # Q1 2026 Update

   ## Project summary
   ACME Platform Initiative is establishing cloud infrastructure for the DataBuddy
   project. Work kicked off 2026-03-29 with initial architecture review.

   ## Timeline so far
   - 2026-03-28: Steering committee approved project charter
   - 2026-03-29: Architecture kickoff meeting scheduled
   - 2026-Q2: Planned platform launch date

   ## Current phase
   Discovery and architecture design (3-4 weeks estimated)

   ## Initial scope
   - AWS infrastructure setup
   - CI/CD pipeline definition
   - Monitoring and logging framework selection
   ```

### Step 10 — Register M365 sources (if applicable)

If the project syncs data from Teams, Outlook, or SharePoint, register those sources.

1. For each M365 source (Teams channel, Outlook folder, SharePoint library):
   - Call `add_sync_source` with:
     - `project_slug`: your project slug
     - `source_type`: `teams`, `outlook`, or `sharepoint`
     - `id`: kebab-case identifier (e.g., `teams-general` or `sp-contracts`)
     - `label`: human-readable name
     - Type-specific fields (channel_id, folder_id, site_url, etc.)

2. **Capture the returned `id` field** — you'll use it in references like `[sp:sp-contracts/file.pdf]`

3. Optional: Call `update_sync_state` to set initial watermarks if you have historical data
   - Use when you want to skip old messages/changes

### Step 11 — Optional: Create the project guide

If your project structure is non-standard or needs explanation:

1. Call `write_file` with path `projects/{slug}/_guide.md`
2. Copy template from `_templates/project-guide.md` and customize:
   - Folder structure explanation (what goes where)
   - Team contacts and responsibilities
   - M365 sync pipeline notes
   - Development environment setup
   - Any project-specific workflows or conventions

### Step 12 — Rebuild folder manifests

Sync the manifests for full discoverability and fresh `_index.yaml` files.

1. Call `update_manifest` for `projects/{slug}/`
2. Call `update_manifest` for `projects/{slug}/correspondence/`
3. Call `update_manifest` for `projects/{slug}/knowledge/`
4. Optional: For each subdirectory with content, call `update_manifest` on it

After this, the project is fully initialized and ready for work.

## Quick verification checklist

- [ ] Slug is kebab-case and globally unique (checked in `list_projects`)
- [ ] `create_project` completed with slug, name, type, status
- [ ] `_status.md` written with current state and next steps
- [ ] `decisions.md` initialized as append-only decision log
- [ ] Key people identified and `@slug` refs collected
- [ ] `link_person_to_project` called for each stakeholder
- [ ] New people/companies created if needed
- [ ] Correspondence folder descriptions updated
- [ ] First entry in `updates/` created with initial timeline
- [ ] M365 sources registered via `add_sync_source` (if applicable)
- [ ] Optional: `_guide.md` created for complex project structure
- [ ] Folder manifests rebuilt via `update_manifest`

## What you can now do

Once all 12 steps are complete:

- ✅ Create knowledge entries in `knowledge/` with validated YAML frontmatter
- ✅ Append decisions to `decisions.md` (use `append_to_file` only)
- ✅ Append updates to `updates/` (use `append_to_file` only)
- ✅ Write correspondence summaries in `correspondence/*`
- ✅ Store external docs in `docs/`
- ✅ Use `get_project_context` to load full project at any time
- ✅ Use `search_files` to find content by keyword
- ✅ Use references like `[sp:sp-contracts/msa.pdf]` in your content

## Common mistakes to avoid

1. **Creating a project with duplicate slug**
   → Solution: Always `list_projects` first and verify uniqueness

2. **Manually editing `people.md` or `companies.md`**
   → These auto-regenerate from `@slug` references. Use link/unlink tools instead.

3. **Using M365 refs before registering source**
   → Example: `[sp:contracts/msa.pdf]` when source `sp` doesn't exist
   → Solution: Call `add_sync_source` first, use returned `id` in references

4. **Putting knowledge entries in `knowledge/` without YAML frontmatter**
   → These will fail validation. Required: `source`, `processed`, `method`

5. **Using `write_file` on append-only paths**
   → Paths `updates/`, `decisions.md` require `append_to_file`
   → Using `write_file` will overwrite the entire file

6. **Forgetting to call `update_manifest`**
   → New files won't appear in `_index.yaml` until you rebuild it
   → Always call `update_manifest` after writing files to a folder

7. **Not including company when creating people**
   → `company` parameter is required. Use "Other" only if genuinely unknown
   → Leaving it empty will produce an error

## Next: Start working on the project

Once initialized, your workflow is:

1. Read project context with `get_project_context` to see what you have
2. Write/append content using appropriate tools
3. Link references using `@person`, `@company`, `[[project]]`, `[mem:...]`, `[sp:...]`
4. For knowledge entries, always include complete YAML frontmatter
5. Use `append_to_file` for `updates/` and `decisions.md`
6. Search and cross-reference with `search_files`, `get_related_files`, `resolve_ref`
