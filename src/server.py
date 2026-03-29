"""Project Memory MCP Server.

Usage:
    python server.py --root /path/to/memory-root

All tools return {"result": ..., "warnings": [...]} or {"error": "...", "warnings": []}.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

import fastmcp

from filesystem import MemoryFS, is_manifest, to_kebab_case, validate_knowledge_frontmatter
from guide import generate_guide
from models import (
    FolderManifest,
    ManifestEntry,
    ProjectMeta,
    ProjectStatus,
    ProjectType,
)
from templates import KNOWLEDGE_ENTRY_TEMPLATE

# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server(root: Path) -> fastmcp.FastMCP:
    root = root.resolve()  # ensure absolute so Path.relative_to() never fails
    fs = MemoryFS(root)
    fs.initialise()

    mcp = fastmcp.FastMCP(
        name="project-memory",
        instructions=(
            "Structured project memory filesystem for long-term LLM memory. "
            "Manages projects, people, companies, correspondence, decisions, and processed "
            "knowledge as plain Markdown and YAML files on disk.\n\n"
            "Read resource memory://guide before using any tool."
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
        """List all projects, optionally filtered by status, type, or tags (comma-separated)."""
        try:
            index = fs.load_projects_index()
            projects = index.projects

            if status:
                projects = [p for p in projects if p.status == status]
            if type:
                projects = [p for p in projects if p.type == type]
            if tags:
                tag_list = [t.strip() for t in tags.split(",")]
                projects = [
                    p for p in projects
                    if any(t in p.tags for t in tag_list)
                ]

            return {
                "result": [p.model_dump() for p in projects],
                "warnings": [],
            }
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def get_project_context(slug: str, deep: bool = False) -> dict[str, Any]:
        """Return project context.

        Lightweight (default): _status.md + _meta.yaml + rendered _index.yaml.
        Deep (deep=True): additionally includes knowledge/_index.yaml manifest
        and people.md content.
        """
        try:
            project_dir = root / "projects" / slug
            if not project_dir.exists():
                return {"error": f"Project {slug!r} not found", "warnings": []}

            warnings: list[str] = []

            # _status.md — always loaded first
            status_path = project_dir / "_status.md"
            status_content = status_path.read_text(encoding="utf-8") if status_path.exists() else None
            if not status_path.exists():
                warnings.append(f"_status.md is missing for project {slug!r}")

            meta_path = project_dir / "_meta.yaml"
            if not meta_path.exists():
                warnings.append(f"_meta.yaml is missing for project {slug!r}")
                meta_content = None
            else:
                meta_content = meta_path.read_text(encoding="utf-8")

            manifest_text = fs.render_manifest(project_dir)

            result: dict[str, Any] = {
                "status": status_content,
                "meta": meta_content,
                "manifest": manifest_text,
            }

            if deep:
                # Knowledge manifest
                knowledge_dir = project_dir / "knowledge"
                result["knowledge_manifest"] = (
                    fs.render_manifest(knowledge_dir) if knowledge_dir.is_dir() else None
                )
                # People file
                people_path = project_dir / "people.md"
                result["people"] = (
                    people_path.read_text(encoding="utf-8") if people_path.exists() else None
                )

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
        """Read a file.  Blocks direct reads of _index.yaml (use get_folder_manifest)."""
        try:
            abs_path = fs._safe_path(path)
            if is_manifest(abs_path):
                return {
                    "error": (
                        "_index.yaml should not be read directly. "
                        "Use get_folder_manifest tool to get a rendered view."
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
        """Write a file with all rules enforced (kebab-case, append-only blocks, manifest update)."""
        try:
            warnings = fs.write_file(path, content, description=description, read_when=read_when)
            return {"result": f"Written: {path}", "warnings": warnings}
        except ValueError as e:
            return {"error": str(e), "warnings": []}
        except Exception as e:
            return {"error": str(e), "warnings": []}

    @mcp.tool
    def append_to_file(path: str, content: str) -> dict[str, Any]:
        """Append content to an append-only file (updates/*.md or decisions.md)."""
        try:
            warnings = fs.append_file(path, content)
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
    ) -> dict[str, Any]:
        """Create a new project with full folder scaffold."""
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
                return {"error": f"Invalid status {status!r}. Must be one of: {valid}", "warnings": []}

            try:
                p_type = ProjectType(type)
            except ValueError:
                valid = [t.value for t in ProjectType]
                return {"error": f"Invalid type {type!r}. Must be one of: {valid}", "warnings": []}

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

            project_dir = fs.scaffold_project(slug, project_meta, description=description)

            return {
                "result": {
                    "slug": slug,
                    "path": str(project_dir.relative_to(root)),
                    "message": f"Project {name!r} created at projects/{slug}",
                },
                "warnings": [],
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
        """Update a project's metadata (status, type, name, tags, etc)."""
        try:
            if status is not None:
                try:
                    ProjectStatus(status)
                except ValueError:
                    valid = [s.value for s in ProjectStatus]
                    return {"error": f"Invalid status {status!r}. Must be one of: {valid}", "warnings": []}

            if type is not None:
                try:
                    ProjectType(type)
                except ValueError:
                    valid = [t.value for t in ProjectType]
                    return {"error": f"Invalid type {type!r}. Must be one of: {valid}", "warnings": []}

            updated = fs.update_project(slug, name=name, status=status, type=type, meta=meta)

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
        """Targeted update of a manifest entry's description/read_when/stale_after."""
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
        company: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a person file in _global/people/ and update its _index.yaml."""
        try:
            kebab = to_kebab_case(slug)
            if kebab != slug:
                return {
                    "error": f"Slug must be kebab-case. Got {slug!r}, expected {kebab!r}",
                    "warnings": [],
                }

            extra: dict[str, Any] = {}
            if title:
                extra["Title"] = title
            if company:
                extra["Company"] = company
            if email:
                extra["Email"] = email
            if phone:
                extra["Phone"] = phone

            path = fs.create_person(slug, name, extra_fields=extra or None, description=description)
            return {
                "result": {
                    "path": fs._rel(path),
                    "message": f"Person {name!r} created",
                },
                "warnings": [],
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
        """Create a company file in _global/companies/ and update its _index.yaml."""
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

            path = fs.create_company(slug, name, extra_fields=extra or None, description=description)
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
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update structured fields for an existing person file."""
        try:
            extra: dict[str, Any] = {}
            if title is not None: extra["Title"] = title
            if company is not None: extra["Company"] = company
            if email is not None: extra["Email"] = email
            if phone is not None: extra["Phone"] = phone

            path = fs.update_person(slug, name=name, extra_fields=extra or None, description=description)
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
        """Update structured fields for an existing company file."""
        try:
            extra: dict[str, Any] = {}
            if industry is not None: extra["Industry"] = industry
            if website is not None: extra["Website"] = website

            path = fs.update_company(slug, name=name, extra_fields=extra or None, description=description)
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

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    @mcp.resource("memory://guide")
    def get_server_guide() -> str:
        """Structural reference for this server — read once per session before using any tool."""
        return generate_guide(mcp, root)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Memory MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python server.py --root ./my-memory
  python server.py --root /home/user/project-memory --transport stdio
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
    args = parser.parse_args()

    server = create_server(args.root)

    if args.transport == "http":
        server.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
