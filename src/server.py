"""Project Memory MCP Server.

Usage:
    python server.py --root /path/to/memory-root

All tools return {"result": ..., "warnings": [...]} or {"error": "...", "warnings": []}.
"""

from __future__ import annotations

import argparse
import os
import secrets
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

import fastmcp
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from filesystem import (
    MemoryFS,
    is_index_yaml,
    is_manifest,
    is_sync_yaml,
    to_kebab_case,
    validate_knowledge_frontmatter,
)
from rag import RAGEngine, RAG_BACKEND_TFIDF, RAG_BACKEND_EMBEDDINGS, DEFAULT_EMBEDDING_MODEL
from guide import (
    generate_guide,
    generate_m365_guide,
    generate_quick_reference,
    generate_skill_guide,
    generate_new_project_setup,
)
from models import (
    FolderManifest,
    ManifestEntry,
    ProjectMeta,
    ProjectStatus,
    ProjectType,
)
from templates import KNOWLEDGE_ENTRY_TEMPLATE

# ---------------------------------------------------------------------------
# Bearer-token auth middleware
# ---------------------------------------------------------------------------


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces Bearer-token authentication."""

    def __init__(self, app, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenMiddleware requires a non-empty token")
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        auth_header = request.headers.get("Authorization", "")
        authenticated = False
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]
            authenticated = secrets.compare_digest(provided, self._token)

        if not authenticated:
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Project Memory MCP"'},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(
    root: Path,
    rag_backend: str = RAG_BACKEND_TFIDF,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> fastmcp.FastMCP:
    root = root.resolve()  # ensure absolute so Path.relative_to() never fails
    fs = MemoryFS(root)
    fs.initialise()
    rag = RAGEngine(root, backend=rag_backend, embedding_model=embedding_model)

    mcp = fastmcp.FastMCP(
        name="project-memory",
        instructions=(
            "Structured project memory filesystem for long-term LLM memory. "
            "Manages projects, people, companies, correspondence, decisions, and processed "
            "knowledge as plain Markdown and YAML files on disk.\n\n"
            "CRITICAL: You are strictly forbidden from executing any tools in this server until you have called `read_resource` with `memory://guide` to understand the data schemas and layout."
        ),
    )

    # -----------------------------------------------------------------------
    # Filesystem tools
    # -----------------------------------------------------------------------

    @mcp.tool
    def list_projects(
        status: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> dict[str, Any]:
        """List all projects, optionally filtered by status, type, or tags (comma-separated).

        🛑 CRITICAL INSTRUCTION: If you have not yet read the resource `memory://guide`
        in this conversation, you MUST do so before attempting to use this tool or
        any other tool in this project memory server!
        """
        try:
            index = fs.load_projects_index()
            projects = index.projects

            if status:
                projects = [p for p in projects if p.status == status]
            if type:
                projects = [p for p in projects if p.type == type]
            if tags:
                tag_list = [t.strip() for t in tags.split(",")]
                projects = [p for p in projects if any(t in p.tags for t in tag_list)]

            return {
                "result": [p.model_dump() for p in projects],
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_project_context(slug: str, deep: bool = False) -> dict[str, Any]:
        """Return project context.

        🛑 CRITICAL INSTRUCTION: If you have not yet read the resource `memory://guide`
        in this conversation, you MUST do so before attempting to use this tool or
        any other tool in this project memory server!

        Lightweight (default): _status.md + _instructions.md + _meta.yaml + rendered _index.yaml.
        Deep (deep=True): additionally includes knowledge/_index.yaml manifest
        and people.md content.

        _instructions.md contains custom LLM behavior rules for this project.
        You MUST follow any instructions defined in that file when working with this project.
        """
        try:
            project_dir = root / "projects" / slug
            if not project_dir.exists():
                return {"error": f"Project {slug!r} not found", "warnings": []}

            warnings: list[str] = []

            # _status.md — always loaded first
            status_path = project_dir / "_status.md"
            status_content = (
                status_path.read_text(encoding="utf-8")
                if status_path.exists()
                else None
            )
            if not status_path.exists():
                warnings.append(f"_status.md is missing for project {slug!r}")

            # _instructions.md — loaded right after status (custom LLM behavior rules)
            instructions_path = project_dir / "_instructions.md"
            instructions_content = (
                instructions_path.read_text(encoding="utf-8")
                if instructions_path.exists()
                else None
            )

            meta_path = project_dir / "_meta.yaml"
            if not meta_path.exists():
                warnings.append(f"_meta.yaml is missing for project {slug!r}")
                meta_content = None
            else:
                meta_content = meta_path.read_text(encoding="utf-8")

            manifest_text = fs.render_manifest(project_dir)

            result: dict[str, Any] = {
                "status": status_content,
                "instructions": instructions_content,
                "meta": meta_content,
                "manifest": manifest_text,
            }

            if deep:
                # Knowledge manifest
                knowledge_dir = project_dir / "knowledge"
                result["knowledge_manifest"] = (
                    fs.render_manifest(knowledge_dir)
                    if knowledge_dir.is_dir()
                    else None
                )
                # People file
                people_path = project_dir / "people.md"
                result["people"] = (
                    people_path.read_text(encoding="utf-8")
                    if people_path.exists()
                    else None
                )
                # Sync state (_sync.yaml) — null if not configured
                sync_result = fs.get_sync_state(slug)
                result["sync"] = sync_result.get("result")

            return {"result": result, "warnings": warnings}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_folder_manifest(folder_path: str) -> dict[str, Any]:
        """Read _index.yaml for a folder and render it as formatted text."""
        try:
            folder = fs._safe_path(folder_path)
            if not folder.is_dir():
                return {"error": f"Folder not found: {folder_path}", "warnings": []}
            text = fs.render_manifest(folder)
            return {"result": text, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def read_file(path: str) -> dict[str, Any]:
        """Read a file.  Blocks direct reads of _index.yaml (use get_folder_manifest) and _sync.yaml (use get_sync_state)."""
        try:
            abs_path = fs._safe_path(path)
            if is_index_yaml(abs_path):
                return {
                    "error": (
                        "_index.yaml should not be read directly. "
                        "Use get_folder_manifest tool to get a rendered view."
                    ),
                    "warnings": [],
                }
            if is_sync_yaml(abs_path):
                return {
                    "error": (
                        "_sync.yaml should not be read directly. "
                        "Use get_sync_state tool to read M365 sync configuration."
                    ),
                    "warnings": [],
                }
            content = fs.read_file(abs_path)
            return {"result": content, "warnings": []}
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def write_file(
        path: str,
        content: str,
        description: Optional[str] = None,
        read_when: Optional[str] = None,
    ) -> dict[str, Any]:
        """Write a file with all rules enforced (kebab-case, append-only blocks, manifest update).

        For existing files, read current content first to avoid unintended overwrite.
        """
        try:
            warnings = fs.write_file(
                path, content, description=description, read_when=read_when
            )
            rag.index_file(fs._safe_path(path))
            return {"result": f"Written: {path}", "warnings": warnings}
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def append_to_file(path: str, content: str) -> dict[str, Any]:
        """Append content to an append-only file (updates/*.md or decisions.md).

        Read the target file first when appending context-sensitive updates.
        """
        try:
            warnings = fs.append_file(path, content)
            rag.index_file(fs._safe_path(path))
            return {"result": f"Appended to: {path}", "warnings": warnings}
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def create_project(
        slug: str,
        name: str,
        status: str = "active",
        type: str = "internal",
        meta: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
        instructions: Optional[str] = None,
        copy_instructions_from: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new project with full folder scaffold.

        IMPORTANT: Before creating the project, ask the user:
        1. Would you like to add custom instructions for how I should behave on this project?
           (e.g., preferred tone, language, domain terminology, response format)
        2. Would you like to copy instructions from an existing project?
           (provide copy_instructions_from="{slug}" if yes)
        3. Do you have other MCP connectors I should use for this project?
           (e.g., GitHub, Jira, Confluence, Linear — these go in the instructions)

        If the user provides custom instructions, pass them via the `instructions` parameter.
        If they want to copy from another project, use `copy_instructions_from`.
        If neither, a default template is scaffolded for later editing.
        """
        try:
            # Validate slug
            kebab = to_kebab_case(slug)
            if kebab != slug:
                return {
                    "error": f"Slug must be kebab-case. Got {slug!r}, expected {kebab!r}",
                    "warnings": [],
                }

            # Check uniqueness
            index = fs.load_projects_index()
            if any(p.slug == slug for p in index.projects):
                return {"error": f"Project {slug!r} already exists", "warnings": []}

            try:
                p_status = ProjectStatus(status)
            except ValueError:
                valid = [s.value for s in ProjectStatus]
                return {
                    "error": f"Invalid status {status!r}. Must be one of: {valid}",
                    "warnings": [],
                }

            try:
                p_type = ProjectType(type)
            except ValueError:
                valid = [t.value for t in ProjectType]
                return {
                    "error": f"Invalid type {type!r}. Must be one of: {valid}",
                    "warnings": [],
                }

            # Resolve instructions content
            instructions_content: Optional[str] = None
            warnings: list[str] = []

            if copy_instructions_from and instructions:
                return {
                    "error": "Cannot use both 'instructions' and 'copy_instructions_from'. Choose one.",
                    "warnings": [],
                }

            if copy_instructions_from:
                source_instructions = root / "projects" / copy_instructions_from / "_instructions.md"
                if not source_instructions.exists():
                    return {
                        "error": f"Source project {copy_instructions_from!r} has no _instructions.md to copy from",
                        "warnings": [],
                    }
                instructions_content = source_instructions.read_text(encoding="utf-8")
                warnings.append(
                    f"Instructions copied from project {copy_instructions_from!r}. "
                    "Review and customize them for this project."
                )
            elif instructions:
                instructions_content = instructions

            today = date.today().isoformat()
            project_meta = ProjectMeta(
                id=str(uuid.uuid4()),
                slug=slug,
                name=name,
                status=p_status,
                type=p_type,
                company=meta.get("company") if meta else None,
                owner=meta.get("owner") if meta else None,
                team=meta.get("team", []) if meta else [],
                tags=meta.get("tags", []) if meta else [],
                created=today,
                updated=today,
            )

            project_dir = fs.scaffold_project(
                slug, project_meta, description=description,
                instructions_content=instructions_content,
            )

            return {
                "result": {
                    "slug": slug,
                    "path": str(project_dir.relative_to(root)),
                    "message": f"Project {name!r} created at projects/{slug}",
                    "has_custom_instructions": bool(instructions_content),
                },
                "warnings": warnings,
            }
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_project(
        slug: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Update a project's metadata (status, type, name, tags, etc).

        Read current project context first before applying metadata changes.
        """
        try:
            if status is not None:
                try:
                    ProjectStatus(status)
                except ValueError:
                    valid = [s.value for s in ProjectStatus]
                    return {
                        "error": f"Invalid status {status!r}. Must be one of: {valid}",
                        "warnings": [],
                    }

            if type is not None:
                try:
                    ProjectType(type)
                except ValueError:
                    valid = [t.value for t in ProjectType]
                    return {
                        "error": f"Invalid type {type!r}. Must be one of: {valid}",
                        "warnings": [],
                    }

            updated = fs.update_project(
                slug, name=name, status=status, type=type, meta=meta
            )

            return {
                "result": {
                    "slug": slug,
                    "message": f"Project {slug!r} updated",
                    "meta": updated.model_dump(),
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def delete_project(slug: str, confirm: bool = False) -> dict[str, Any]:
        """Soft-delete an entire project. Must set confirm=true."""
        try:
            if not confirm:
                return {
                    "error": "Destructive operation. You must ask the user for permission and then set confirm=true.",
                    "warnings": [],
                }

            trash_path = fs.delete_project(slug)
            return {
                "result": f"Project {slug!r} moved to trash: {trash_path}",
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def create_knowledge_entry(
        project_slug: str,
        topic: str,
        content: str,
        frontmatter: dict[str, Any],
        description: Optional[str] = None,
        read_when: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a knowledge entry with validated frontmatter in projects/{slug}/knowledge/."""
        try:
            kebab_topic = to_kebab_case(topic)
            # Build frontmatter YAML string
            import yaml

            fm_str = yaml.dump(frontmatter, default_flow_style=False).strip()
            full_content = f"---\n{fm_str}\n---\n\n# {topic}\n\n{content}"

            valid, fm_errors = validate_knowledge_frontmatter(full_content)
            if not valid:
                return {"error": "; ".join(fm_errors), "warnings": []}

            path = f"projects/{project_slug}/knowledge/{kebab_topic}.md"
            warnings = fs.write_file(
                path, full_content, description=description, read_when=read_when
            )
            rag.index_file(fs._safe_path(path))
            return {"result": f"Knowledge entry created: {path}", "warnings": warnings}
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_manifest(folder_path: str) -> dict[str, Any]:
        """Rebuild _index.yaml for a folder, adding placeholders for unindexed files."""
        try:
            folder = fs._safe_path(folder_path)
            if not folder.is_dir():
                return {"error": f"Folder not found: {folder_path}", "warnings": []}
            manifest = fs.rebuild_manifest(folder)
            return {
                "result": f"Manifest rebuilt for {folder_path}: {len(manifest.files)} entries",
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_file_description(
        folder_path: str,
        filename: str,
        description: str,
        read_when: Optional[str] = None,
        stale_after: Optional[str] = None,
    ) -> dict[str, Any]:
        """Targeted update of a manifest entry's description/read_when/stale_after.

        Read the folder manifest first to avoid overwriting a newer description.
        """
        try:
            folder = fs._safe_path(folder_path)
            if not folder.is_dir():
                return {"error": f"Folder not found: {folder_path}", "warnings": []}

            kwargs: dict[str, Any] = {"description": description}
            if read_when is not None:
                kwargs["read_when"] = read_when
            if stale_after is not None:
                kwargs["stale_after"] = stale_after

            found = fs.update_manifest_entry(folder, filename, **kwargs)
            if not found:
                # Create entry if it doesn't exist yet
                fs.add_manifest_entry(
                    folder,
                    ManifestEntry(
                        name=filename,
                        description=description,
                        read_when=read_when,
                        stale_after=stale_after,
                    ),
                )
                return {
                    "result": f"New manifest entry created for {filename}",
                    "warnings": [],
                }
            return {
                "result": f"Manifest entry updated for {filename}",
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def resolve_ref(slug: str) -> dict[str, Any]:
        """Resolve @slug to a global entity (person or company) and return its content."""
        try:
            path, content = fs.resolve_ref(slug)
            return {
                "result": {
                    "path": fs._rel(path),
                    "content": content,
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_refs_for(ref: str) -> dict[str, Any]:
        """Return all files that mention @ref, #tag, or [[link]]."""
        try:
            files = fs.get_refs_for(ref)
            return {"result": files, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def search_files(
        keyword: str,
        project_slug: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search .md files for keyword.  Returns path, line number, and matching line.

        Prefer ``project_slug`` to scope search to a project.
        ``folder`` is a lower-level filter for arbitrary sub-paths.
        """
        try:
            results = fs.search_files(keyword, project_slug=project_slug, folder=folder)
            return {"result": results, "warnings": []}
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def delete_file(path: str) -> dict[str, Any]:
        """Soft-delete a file (move to _trash/).  Removes manifest entry."""
        try:
            trash_path = fs.soft_delete(path)
            return {
                "result": f"Moved to trash: {trash_path}",
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def list_stale_manifests() -> dict[str, Any]:
        """Return all folder paths where _index.yaml has stale: true."""
        try:
            stale = fs.list_stale_manifests()
            return {"result": stale, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    # -----------------------------------------------------------------------
    # Global entity tools
    # -----------------------------------------------------------------------

    @mcp.tool
    def create_person(
        slug: str,
        name: str,
        title: Optional[str] = None,
        company: str = "",
        email: Optional[str] = None,
        phone: Optional[str] = None,
        global_description: Optional[str] = None,
        project_slug: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a global person profile and update _global/people/_index.yaml.

        Before creating, check existing entities first with list_global_people
        (and optionally list_global_companies / resolve_ref) to avoid duplicates.
        company is required. Use "Other" only when the company is genuinely unknown.
        Populate title/email/phone/global_description whenever available.
        Optionally set project_slug to link the new person to an existing project.
        """
        try:
            kebab = to_kebab_case(slug)
            if kebab != slug:
                return {
                    "error": f"Slug must be kebab-case. Got {slug!r}, expected {kebab!r}",
                    "warnings": [],
                }

            if project_slug is not None:
                project_kebab = to_kebab_case(project_slug)
                if project_kebab != project_slug:
                    return {
                        "error": f"project_slug must be kebab-case. Got {project_slug!r}, expected {project_kebab!r}",
                        "warnings": [],
                    }

                project_dir = root / "projects" / project_slug
                if not project_dir.exists():
                    return {
                        "error": f"Project {project_slug!r} not found",
                        "warnings": [],
                    }

            company_value = company.strip()
            if not company_value:
                return {
                    "error": "company is required (use 'Other' only if genuinely unknown)",
                    "warnings": [],
                }

            extra: dict[str, Any] = {}
            if title:
                extra["Title"] = title
            extra["Company"] = company_value
            if email:
                extra["Email"] = email
            if phone:
                extra["Phone"] = phone
            if global_description:
                extra["Description"] = global_description

            warnings: list[str] = []
            if company_value.lower() == "other":
                warnings.append(
                    "Company set to 'Other'. Use a specific company whenever possible."
                )

            missing_fields: list[str] = []
            if not title:
                missing_fields.append("title")
            if not email:
                missing_fields.append("email")
            if not phone:
                missing_fields.append("phone")
            if not global_description:
                missing_fields.append("global_description")
            if missing_fields:
                warnings.append(
                    "Person profile is sparse. Consider adding: "
                    + ", ".join(missing_fields)
                )

            path = fs.create_person(
                slug, name, extra_fields=extra or None, description=description
            )
            if project_slug is not None:
                fs.link_person_to_project(slug, project_slug)

            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Person {name!r} created",
                    "linked_project": project_slug,
                },
                "warnings": warnings,
            }
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def create_company(
        slug: str,
        name: str,
        industry: Optional[str] = None,
        website: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a company file in _global/companies/ and update its _index.yaml.

        Before creating, check existing entities first with list_global_companies
        (and optionally list_global_people / resolve_ref) to avoid duplicates.
        """
        try:
            kebab = to_kebab_case(slug)
            if kebab != slug:
                return {
                    "error": f"Slug must be kebab-case. Got {slug!r}, expected {kebab!r}",
                    "warnings": [],
                }

            extra: dict[str, Any] = {}
            if industry:
                extra["Industry"] = industry
            if website:
                extra["Website"] = website

            path = fs.create_company(
                slug, name, extra_fields=extra or None, description=description
            )
            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Company {name!r} created",
                },
                "warnings": [],
            }
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_person(
        slug: str,
        name: Optional[str] = None,
        title: Optional[str] = None,
        company: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        global_description: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update structured fields for a global person profile and sync linked projects.

        Read the person profile first with get_person to avoid overriding manual notes context.
        """
        try:
            extra: dict[str, Any] = {}
            if title is not None:
                extra["Title"] = title
            if company is not None:
                extra["Company"] = company
            if email is not None:
                extra["Email"] = email
            if phone is not None:
                extra["Phone"] = phone
            if global_description is not None:
                extra["Description"] = global_description

            path = fs.update_person(
                slug, name=name, extra_fields=extra or None, description=description
            )
            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Person {slug!r} updated",
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_company(
        slug: str,
        name: Optional[str] = None,
        industry: Optional[str] = None,
        website: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update structured fields for an existing company file.

        Read the company profile first with get_company before modifying fields.
        """
        try:
            extra: dict[str, Any] = {}
            if industry is not None:
                extra["Industry"] = industry
            if website is not None:
                extra["Website"] = website

            path = fs.update_company(
                slug, name=name, extra_fields=extra or None, description=description
            )
            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Company {slug!r} updated",
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_person(slug: str) -> dict[str, Any]:
        """Read a person file from _global/people/{slug}.md."""
        try:
            path = root / "_global" / "people" / f"{slug}.md"
            if not path.exists():
                return {"error": f"Person {slug!r} not found", "warnings": []}
            content = path.read_text(encoding="utf-8")
            return {"result": content, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_company(slug: str) -> dict[str, Any]:
        """Read a company file from _global/companies/{slug}.md."""
        try:
            path = root / "_global" / "companies" / f"{slug}.md"
            if not path.exists():
                return {"error": f"Company {slug!r} not found", "warnings": []}
            content = path.read_text(encoding="utf-8")
            return {"result": content, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def list_global_people() -> dict[str, Any]:
        """List all people in _global/people/ from the manifest."""
        try:
            people = fs.list_global_people()
            return {"result": people, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def list_global_companies() -> dict[str, Any]:
        """List all companies in _global/companies/ from the manifest."""
        try:
            companies = fs.list_global_companies()
            return {"result": companies, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def link_person_to_project(person_slug: str, project_slug: str) -> dict[str, Any]:
        """Create a person-project relationship and sync global + project people views."""
        try:
            person_path, project_people_path = fs.link_person_to_project(
                person_slug, project_slug
            )
            return {
                "result": {
                    "person": fs._rel(person_path),
                    "project_people": fs._rel(project_people_path),
                    "message": f"Linked @{person_slug} to [[{project_slug}]]",
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def unlink_person_from_project(
        person_slug: str, project_slug: str
    ) -> dict[str, Any]:
        """Remove a person-project relationship and sync global + project people views."""
        try:
            person_path, project_people_path = fs.unlink_person_from_project(
                person_slug, project_slug
            )
            return {
                "result": {
                    "person": fs._rel(person_path),
                    "project_people": fs._rel(project_people_path),
                    "message": f"Unlinked @{person_slug} from [[{project_slug}]]",
                },
                "warnings": [],
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def edit_person_notes(
        slug: str,
        notes: str,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Edit manual notes in a global person profile.

        First call get_person(slug) to preserve existing note context.
        Use this tool only when the user explicitly asks to add or modify manual notes.
        """
        try:
            path, warnings = fs.edit_person_notes(slug=slug, notes=notes, mode=mode)
            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Manual notes updated for person {slug!r} using mode={mode!r}",
                },
                "warnings": warnings,
            }
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    # -----------------------------------------------------------------------
    # RAG / semantic-search tools
    # -----------------------------------------------------------------------

    @mcp.tool
    def semantic_search(
        query: str,
        project_slug: Optional[str] = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search indexed files by semantic meaning.

        Uses the configured RAG backend (``tfidf`` or ``embeddings``) to rank
        results by relevance.  Returns up to *top_k* results ordered by score.
        Each result contains ``path``, ``score`` (0–1), and ``indexed_at``
        timestamp.

        Use *project_slug* to scope the search to a single project.

        If the index is empty or results are unexpected, run
        ``rebuild_rag_index`` first to (re-)index all files.
        """
        try:
            # Auto-detect and re-index externally modified files before searching
            stale = rag.get_stale_files()
            reindexed = []
            for entry in stale:
                p = root / entry["path"]
                result = rag.index_file(p)
                if result == "indexed":
                    reindexed.append(entry["path"])

            results = rag.search(query, project_slug=project_slug, top_k=top_k)
            warnings: list[str] = []
            if reindexed:
                warnings.append(
                    f"Re-indexed {len(reindexed)} externally modified file(s) before search: "
                    + ", ".join(reindexed)
                )
            if not results:
                warnings.append(
                    "No results found. If files have not been indexed yet, "
                    "call rebuild_rag_index first."
                )
            return {
                "result": results,
                "backend": rag.backend,
                "warnings": warnings,
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def rebuild_rag_index(
        project_slug: Optional[str] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Build or refresh the local RAG index used by ``semantic_search``.

        * By default only re-indexes files whose on-disk content has changed
          since the last run (fast incremental update).
        * Set *force* to ``true`` to re-index every file unconditionally.
        * Optionally scope to a single project with *project_slug*.

        The active backend (``tfidf`` or ``embeddings``) is reported in the
        result.  Returns counts of ``indexed``, ``skipped``, and ``stale``
        files.  Stale files are those that were externally modified (outside
        the MCP server) and have now been re-indexed.
        """
        try:
            counts = rag.rebuild(project_slug=project_slug, force=force)
            total = counts["indexed"] + counts["skipped"] + counts["stale"]
            return {
                "result": {
                    "backend": rag.backend,
                    "total_files": total,
                    "indexed": counts["indexed"],
                    "re_indexed_stale": counts["stale"],
                    "skipped_unchanged": counts["skipped"],
                    "index_size": rag.indexed_count(),
                },
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def rebuild_refs_index() -> dict[str, Any]:
        """Rebuild _refs-index.json by scanning all .md files from scratch."""
        try:
            count = fs.rebuild_refs_index()
            return {
                "result": f"Refs index rebuilt: {count} files indexed",
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_related_files(path: str) -> dict[str, Any]:
        """Return bidirectional cross-reference map for a file.

        Shows:
          - referenced_by: files that link to this file via [mem:path]
          - references: files that this file links to via [mem:...]
          - m365_refs: M365 source tokens ([sp:], [tm:], [ol:]) in this file

        Use this to trace how a piece of content relates to its sources
        (M365 documents, Teams threads, email threads) and to other internal
        workspace files (knowledge entries, correspondence, notes, updates).
        """
        try:
            result = fs.get_related_files(path)
            return {"result": result, "warnings": []}
        except FileNotFoundError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    # -----------------------------------------------------------------------
    # Sync state tools (M365 integration)
    # -----------------------------------------------------------------------

    @mcp.tool
    def get_sync_state(project_slug: str) -> dict[str, Any]:
        """Read _sync.yaml for a project.  Returns null result with warning if missing."""
        try:
            return fs.get_sync_state(project_slug)
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def update_sync_state(
        project_slug: str,
        source_type: str,
        source_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update watermark fields for a specific source after pipeline processing.

        source_type: "teams" | "outlook" | "sharepoint" | "pipeline"
        source_id: the id field of the source to update (ignored for pipeline)
        fields: dict of allowed fields to merge into the source entry
        """
        try:
            return fs.update_sync_state(project_slug, source_type, source_id, fields)
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def add_sync_source(
        project_slug: str,
        source_type: str,
        id: str,
        label: str,
        channel_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        site_url: Optional[str] = None,
        library: Optional[str] = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Register a new M365 source for a project.

        source_type: "teams" | "outlook" | "sharepoint"
        id: kebab-case, unique within source_type for this project
        label: human-readable name
        For teams: channel_id required.
        For outlook: folder_id required.
        For sharepoint: site_url and library required.
        """
        try:
            kwargs: dict[str, Any] = {}
            if channel_id is not None:
                kwargs["channel_id"] = channel_id
            if folder_id is not None:
                kwargs["folder_id"] = folder_id
            if site_url is not None:
                kwargs["site_url"] = site_url
            if library is not None:
                kwargs["library"] = library
            return fs.add_sync_source(
                project_slug, source_type, id=id, label=label, enabled=enabled, **kwargs
            )
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def list_projects_due_for_sync(
        frequency: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return projects where a sync run is overdue.

        frequency: "daily" | "weekly" | null (returns all overdue regardless of frequency)
        """
        try:
            results = fs.list_projects_due_for_sync(frequency=frequency)
            return {"result": results, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def list_projects_due_for_synthesis() -> dict[str, Any]:
        """Return projects where a knowledge synthesis run is overdue."""
        try:
            results = fs.list_projects_due_for_synthesis()
            return {"result": results, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def resolve_m365_ref(project_slug: str, ref: str) -> dict[str, Any]:
        """Resolve an M365 reference token to its full metadata.

        ref: e.g. "sp:sp-contracts/msa-v2.pdf" or "[sp:sp-contracts/msa-v2.pdf]"
        Never calls M365 directly — returns local metadata only (m365_available: false).
        """
        try:
            result = fs.resolve_m365_ref(project_slug, ref)
            if "error" in result:
                return {"error": result["error"], "warnings": []}
            return {"result": result, "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def resolve_mcp_ref(ref: str, project_slug: Optional[str] = None) -> dict[str, Any]:
        """Resolve a generic MCP reference token to its local cross-reference metadata.

        ref: e.g. "mcp:github/repos/acme/backend" or "[mcp:jira/issues/PROJ-123]"

        Returns files that reference this MCP server/resource.
        Unlike M365 refs, generic MCP refs do not require source registration.
        They are advisory tokens — use them to document which external MCP servers
        and resources are relevant to project content.

        If the named MCP server is available in this session, you should use its
        tools to fetch the referenced resource. If not available, the ref still
        documents the dependency for future sessions.
        """
        try:
            # Strip brackets if present
            clean = ref.strip().lstrip("[").rstrip("]")
            if clean.startswith("mcp:"):
                clean = clean[4:]

            parts = clean.split("/", 1)
            server = parts[0]
            resource = parts[1] if len(parts) > 1 else None

            # Find files that reference this MCP server
            refs_index = fs.load_refs_index()
            referencing_files: list[dict[str, Any]] = []

            for entry_path, entry in refs_index.entries.items():
                # Filter by project if specified
                if project_slug and not entry_path.startswith(f"projects/{project_slug}/"):
                    continue

                for mcp_ref in entry.mcp_refs:
                    if mcp_ref.server == server:
                        if resource is None or mcp_ref.resource == resource:
                            referencing_files.append({
                                "path": entry_path,
                                "server": mcp_ref.server,
                                "resource": mcp_ref.resource,
                            })

            return {
                "result": {
                    "server": server,
                    "resource": resource,
                    "referencing_files": referencing_files,
                    "hint": (
                        f"If the MCP server '{server}' is available in this session, "
                        f"use its tools to access the referenced resource. "
                        f"If not available, treat this as documentation of an external dependency."
                    ),
                },
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    @mcp.resource("memory://guide")
    def get_server_guide() -> str:
        """Structural reference for this server — read once per session before using any tool."""
        return generate_guide(mcp, root)

    @mcp.resource("memory://m365")
    def get_m365_guide() -> str:
        """M365 integration reference — source registration, reference syntax, sync state tools."""
        return generate_m365_guide(mcp, root)

    @mcp.resource("memory://quick-reference")
    def get_quick_reference() -> str:
        """Quick reference for tokens, filesystem rules, and tool parameters."""
        return generate_quick_reference(mcp, root)

    @mcp.resource("memory://skill")
    def get_skill_guide() -> str:
        """Skill pre-flight checklist and key rules to keep in mind before using any tool."""
        return generate_skill_guide(mcp, root)

    @mcp.resource("memory://new-project")
    def get_new_project_setup() -> str:
        """Step-by-step guide for initializing a new project — read this when creating a project."""
        return generate_new_project_setup(mcp, root)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Load .env from the working directory (silently ignored if absent).
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Project Memory MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python server.py --root ./my-memory
  python server.py --root /home/user/project-memory --transport stdio
  python server.py --root ./my-memory --transport http --host 0.0.0.0 --port 8000
""",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("./memory-root"),
        help="Path to the memory root directory (default: ./memory-root)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--rag-backend",
        choices=[RAG_BACKEND_TFIDF, RAG_BACKEND_EMBEDDINGS],
        default=RAG_BACKEND_TFIDF,
        dest="rag_backend",
        help=(
            "RAG retrieval backend (default: tfidf). "
            "'embeddings' requires: pip install sentence-transformers"
        ),
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        dest="embedding_model",
        help=(
            "Sentence-Transformers model name used with --rag-backend=embeddings "
            f"(default: {DEFAULT_EMBEDDING_MODEL})"
        ),
    )
    args = parser.parse_args()

    server = create_server(
        args.root,
        rag_backend=args.rag_backend,
        embedding_model=args.embedding_model,
    )

    if args.transport == "http":
        auth_token = os.environ.get("AUTH_TOKEN", "").strip()

        if auth_token:
            from starlette.middleware import Middleware

            http_middleware = [
                Middleware(BearerTokenMiddleware, token=auth_token)
            ]
            print("[auth] Bearer token auth enabled")
        else:
            http_middleware = None
            print("[auth] WARNING: No AUTH_TOKEN set — HTTP transport is unprotected!")

        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            middleware=http_middleware,
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
