"""Filesystem engine for the Project Memory MCP server.

All path operations are relative to a configurable root directory.
No MCP coupling — pure filesystem logic.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from models import (
    FolderManifest,
    KnowledgeFrontmatter,
    ManifestEntry,
    ProjectIndexEntry,
    ProjectMeta,
    ProjectsIndex,
    RefsIndex,
    RefsIndexEntry,
    RootManifest,
    RootManifestEntry,
)
from templates import (
    COMPANY_TEMPLATE,
    EMPTY_MANIFEST,
    KNOWLEDGE_ENTRY_TEMPLATE,
    PERSON_TEMPLATE,
    PROJECT_GUIDE_TEMPLATE,
    PROJECT_META_TEMPLATE,
    PROJECT_STATUS_TEMPLATE,
    ROOT_MANIFEST_TEMPLATE,
    UPDATES_MANIFEST_TEMPLATE,
)

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REF_RE = re.compile(r"@([a-z0-9-]+)")
_TAG_RE = re.compile(r"#([a-z0-9-]+)")
_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return date.today().isoformat()


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_kebab_case(name: str) -> str:
    """Convert a string to kebab-case.  Raises ValueError if not convertible."""
    # strip extension, convert, re-attach
    p = Path(name)
    stem = p.stem
    ext = p.suffix

    converted = stem.lower()
    converted = re.sub(r"[_\s]+", "-", converted)
    converted = re.sub(r"[^a-z0-9-]", "", converted)
    converted = re.sub(r"-+", "-", converted).strip("-")

    if not converted:
        raise ValueError(f"Cannot convert {name!r} to kebab-case")

    result = converted + ext
    return result


def validate_date(s: str) -> bool:
    """Return True if s is a valid YYYY-MM-DD date string."""
    if not _DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def is_append_only(path: Path) -> bool:
    """Return True if path should only allow appends (updates/*.md, decisions.md)."""
    parts = path.parts
    if path.name == "decisions.md":
        return True
    if len(parts) >= 2 and parts[-2] == "updates" and path.suffix == ".md":
        return True
    return False


def is_manifest(path: Path) -> bool:
    """Return True if path is a _index.yaml (protected from direct write)."""
    return path.name == "_index.yaml"


def is_updates_folder(folder: Path) -> bool:
    """Return True if folder is an updates/ subdirectory."""
    return folder.name == "updates"


def parse_refs(content: str) -> dict[str, list[str]]:
    """Parse @refs, #tags, [[links]] from markdown content."""
    refs = list(set(_REF_RE.findall(content)))
    tags = list(set(_TAG_RE.findall(content)))
    links = list(set(_LINK_RE.findall(content)))
    return {"refs": refs, "tags": tags, "links": links}


def validate_knowledge_frontmatter(content: str) -> tuple[bool, list[str]]:
    """Validate that knowledge entry starts with valid YAML frontmatter."""
    errors: list[str] = []
    if not content.startswith("---"):
        errors.append("Knowledge entries must start with a YAML frontmatter block (---)")
        return False, errors

    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append("Frontmatter block is not properly closed with ---")
        return False, errors

    try:
        fm_data = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        errors.append(f"Frontmatter YAML parse error: {e}")
        return False, errors

    if fm_data is None:
        fm_data = {}

    try:
        KnowledgeFrontmatter(**fm_data)
    except Exception as e:
        errors.append(f"Frontmatter validation error: {e}")
        return False, errors

    return True, []


# ---------------------------------------------------------------------------
# MemoryFS
# ---------------------------------------------------------------------------

class MemoryFS:
    """All filesystem operations for the memory root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _safe_path(self, rel_or_abs: str | Path) -> Path:
        """Resolve path inside root.  Raises ValueError if outside root."""
        p = Path(rel_or_abs)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.root / p).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise ValueError(f"Path {rel_or_abs!r} escapes the memory root")
        return resolved

    def _rel(self, abs_path: Path) -> str:
        """Return path relative to root as a forward-slash string (cross-platform)."""
        return abs_path.relative_to(self.root).as_posix()

    # ------------------------------------------------------------------
    # Root initialisation
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Create root structure if it does not already exist."""
        self.root.mkdir(parents=True, exist_ok=True)

        # _projects-index.json
        pi_path = self.root / "_projects-index.json"
        if not pi_path.exists():
            pi_path.write_text(
                json.dumps({"projects": []}, indent=2), encoding="utf-8"
            )

        # _refs-index.json
        ri_path = self.root / "_refs-index.json"
        if not ri_path.exists():
            ri_path.write_text(
                json.dumps({"entries": {}}, indent=2), encoding="utf-8"
            )

        # root _index.yaml
        root_manifest = self.root / "_index.yaml"
        if not root_manifest.exists():
            root_manifest.write_text(
                ROOT_MANIFEST_TEMPLATE.format(date=_today()), encoding="utf-8"
            )

        # _global/
        for sub in ("people", "companies"):
            folder = self.root / "_global" / sub
            folder.mkdir(parents=True, exist_ok=True)
            manifest = folder / "_index.yaml"
            if not manifest.exists():
                manifest.write_text(
                    EMPTY_MANIFEST.format(date=_today()), encoding="utf-8"
                )

        global_manifest = self.root / "_global" / "_index.yaml"
        if not global_manifest.exists():
            global_manifest.write_text(
                EMPTY_MANIFEST.format(date=_today()), encoding="utf-8"
            )

        # _templates/ (written to disk for reference)
        templates_dir = self.root / "_templates"
        templates_dir.mkdir(exist_ok=True)

        tpl_files = {
            "project-guide.md": PROJECT_GUIDE_TEMPLATE,
            "project-meta.yaml": PROJECT_META_TEMPLATE,
            "person.md": PERSON_TEMPLATE,
            "company.md": COMPANY_TEMPLATE,
            "knowledge-entry.md": KNOWLEDGE_ENTRY_TEMPLATE,
        }
        for fname, content in tpl_files.items():
            tpl_path = templates_dir / fname
            if not tpl_path.exists():
                tpl_path.write_text(content, encoding="utf-8")

        # projects/ directory
        (self.root / "projects").mkdir(exist_ok=True)

        # _trash/ directory
        (self.root / "_trash").mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def load_projects_index(self) -> ProjectsIndex:
        path = self.root / "_projects-index.json"
        if not path.exists():
            return ProjectsIndex()
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectsIndex(**data)

    def save_projects_index(self, index: ProjectsIndex) -> None:
        path = self.root / "_projects-index.json"
        path.write_text(
            json.dumps(index.model_dump(), indent=2), encoding="utf-8"
        )

    def load_refs_index(self) -> RefsIndex:
        path = self.root / "_refs-index.json"
        if not path.exists():
            return RefsIndex()
        data = json.loads(path.read_text(encoding="utf-8"))
        return RefsIndex(**data)

    def save_refs_index(self, index: RefsIndex) -> None:
        path = self.root / "_refs-index.json"
        path.write_text(
            json.dumps(index.model_dump(), indent=2), encoding="utf-8"
        )

    def update_refs_for_file(self, rel_path: str, content: str) -> None:
        """Parse content for refs/tags/links and update _refs-index.json."""
        parsed = parse_refs(content)
        refs_index = self.load_refs_index()
        refs_index.entries[rel_path] = RefsIndexEntry(
            path=rel_path, **parsed
        )
        self.save_refs_index(refs_index)

    # ------------------------------------------------------------------
    # Manifest management
    # ------------------------------------------------------------------

    def load_manifest(self, folder: Path) -> FolderManifest:
        manifest_path = folder / "_index.yaml"
        if not manifest_path.exists():
            return FolderManifest(last_updated=_today())
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        return FolderManifest(
            last_updated=raw.get("last_updated", _today()),
            stale=raw.get("stale", False),
            description=raw.get("description"),
            last_entry_date=raw.get("last_entry_date"),
            files=[ManifestEntry(**f) for f in raw.get("files", [])],
        )

    def save_manifest(self, folder: Path, manifest: FolderManifest) -> None:
        manifest_path = folder / "_index.yaml"
        data: dict[str, Any] = {
            "last_updated": manifest.last_updated,
            "stale": manifest.stale,
        }
        if manifest.description is not None:
            data["description"] = manifest.description
        if manifest.last_entry_date is not None:
            data["last_entry_date"] = manifest.last_entry_date
        data["files"] = [e.model_dump() for e in manifest.files]
        header = "# Auto-managed by the MCP server. Edit descriptions via update_file_description tool.\n"
        manifest_path.write_text(
            header + yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def add_manifest_entry(self, folder: Path, entry: ManifestEntry) -> None:
        manifest = self.load_manifest(folder)
        # Replace if entry with same name already exists
        manifest.files = [f for f in manifest.files if f.name != entry.name]
        manifest.files.append(entry)
        manifest.last_updated = _today()
        self.save_manifest(folder, manifest)

    def update_manifest_entry(
        self,
        folder: Path,
        filename: str,
        **kwargs: Any,
    ) -> bool:
        """Update specific fields of a manifest entry.  Returns True if found."""
        manifest = self.load_manifest(folder)
        for entry in manifest.files:
            if entry.name == filename:
                for k, v in kwargs.items():
                    if hasattr(entry, k):
                        setattr(entry, k, v)
                manifest.last_updated = _today()
                self.save_manifest(folder, manifest)
                return True
        return False

    def rebuild_manifest(self, folder: Path) -> FolderManifest:
        """Scan folder, add missing entries, remove entries for deleted files."""
        manifest = self.load_manifest(folder)

        # updates/ folders use a summary-only convention — no per-file tracking
        if is_updates_folder(folder):
            manifest.last_updated = _today()
            manifest.stale = False
            if not manifest.description:
                manifest.description = "Chronological update log. Read the file directly for recent entries."
            self.save_manifest(folder, manifest)
            return manifest

        existing_names = {e.name for e in manifest.files}

        # Add missing entries
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix in (".md", ".yaml", ".json") and not p.name.startswith("_"):
                if p.name not in existing_names:
                    manifest.files.append(ManifestEntry(name=p.name))

        # Remove entries for deleted files
        manifest.files = [
            e for e in manifest.files
            if (folder / e.name).exists()
        ]

        manifest.last_updated = _today()
        manifest.stale = False
        self.save_manifest(folder, manifest)
        return manifest

    def mark_manifest_stale(self, folder: Path) -> None:
        manifest = self.load_manifest(folder)
        if not manifest.stale:
            manifest.stale = True
            self.save_manifest(folder, manifest)

    def render_manifest(self, folder: Path) -> str:
        """Render _index.yaml as human-readable text for LLM consumption."""
        manifest = self.load_manifest(folder)
        rel = self._rel(folder)
        lines = [
            f"## Folder Manifest: {rel}",
            f"Last updated: {manifest.last_updated}",
            f"Stale: {manifest.stale}",
        ]
        if manifest.description:
            lines.append(f"Description: {manifest.description}")
        if manifest.last_entry_date:
            lines.append(f"Last entry date: {manifest.last_entry_date}")
        lines.append("")
        if not manifest.files:
            lines.append("_(no files indexed)_")
        else:
            for entry in manifest.files:
                lines.append(f"### `{entry.name}`")
                lines.append(f"**Description:** {entry.description or '_(not set)_'}")
                if entry.read_when:
                    lines.append(f"**Read when:** {entry.read_when}")
                if entry.stale_after:
                    lines.append(f"**Stale after:** {entry.stale_after}")
                lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Root manifest helpers
    # ------------------------------------------------------------------

    def _load_root_manifest(self) -> RootManifest:
        path = self.root / "_index.yaml"
        if not path.exists():
            return RootManifest(last_updated=_today())
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return RootManifest(
            last_updated=raw.get("last_updated", _today()),
            projects=[RootManifestEntry(**p) for p in raw.get("projects", [])],
        )

    def _save_root_manifest(self, manifest: RootManifest) -> None:
        path = self.root / "_index.yaml"
        data: dict[str, Any] = {
            "last_updated": manifest.last_updated,
            "projects": [p.model_dump() for p in manifest.projects],
        }
        header = "# Auto-managed by the MCP server. Lists all projects.\n"
        path.write_text(
            header + yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Project scaffold
    # ------------------------------------------------------------------

    def scaffold_project(
        self,
        slug: str,
        meta: ProjectMeta,
        description: Optional[str] = None,
    ) -> Path:
        """Create the full project folder tree."""
        project_dir = self.root / "projects" / slug
        if project_dir.exists():
            raise ValueError(f"Project {slug!r} already exists")

        today = _today()

        # Create sub-folders
        sub_folders = ["knowledge", "correspondence", "updates", "docs", "notes"]
        for sub in sub_folders:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        # _index.yaml skeletons
        for sub in sub_folders:
            if sub == "updates":
                (project_dir / sub / "_index.yaml").write_text(
                    UPDATES_MANIFEST_TEMPLATE.format(date=today), encoding="utf-8"
                )
            else:
                (project_dir / sub / "_index.yaml").write_text(
                    EMPTY_MANIFEST.format(date=today), encoding="utf-8"
                )
        (project_dir / "_index.yaml").write_text(
            EMPTY_MANIFEST.format(date=today), encoding="utf-8"
        )

        # _status.md (always-current project status — first loaded in context)
        (project_dir / "_status.md").write_text(
            PROJECT_STATUS_TEMPLATE.format(name=meta.name, date=today), encoding="utf-8"
        )

        # _guide.md (static, human-editable)
        (project_dir / "_guide.md").write_text(PROJECT_GUIDE_TEMPLATE, encoding="utf-8")

        # _meta.yaml
        meta_content = PROJECT_META_TEMPLATE.format(
            id=meta.id,
            slug=meta.slug,
            name=meta.name,
            status=meta.status.value,
            type=meta.type.value,
            created=meta.created,
            updated=meta.updated,
        )
        (project_dir / "_meta.yaml").write_text(meta_content, encoding="utf-8")

        # Core markdown files
        core_files = {
            "people.md": f"# People — {meta.name}\n\n",
            "companies.md": f"# Companies — {meta.name}\n\n",
            "decisions.md": f"# Decisions — {meta.name}\n\n",
        }
        for fname, content in core_files.items():
            (project_dir / fname).write_text(content, encoding="utf-8")

        # correspondence sub-files
        for fname in ("email-threads.md", "calls.md", "messages.md"):
            (project_dir / "correspondence" / fname).write_text(
                f"# {fname.replace('-', ' ').title()} — {meta.name}\n\n",
                encoding="utf-8",
            )

        # Populate project _index.yaml with core file entries
        project_manifest = self.load_manifest(project_dir)
        core_entries = [
            ManifestEntry(
                name="_status.md",
                description=f"Always-current project status for {meta.name}.",
                read_when="First — before loading any other context for this project.",
            ),
            ManifestEntry(
                name="people.md",
                description=f"Key contacts and stakeholders for {meta.name}.",
                read_when="Before any communication or meeting.",
            ),
            ManifestEntry(
                name="companies.md",
                description=f"Company relationships relevant to {meta.name}.",
                read_when="When researching company context.",
            ),
            ManifestEntry(
                name="decisions.md",
                description=f"Architecture and key decisions log for {meta.name} (append-only).",
                read_when="Before making decisions that may overlap.",
            ),
        ]
        project_manifest.files = core_entries
        if description:
            project_manifest.files.insert(
                0,
                ManifestEntry(
                    name="_meta.yaml",
                    description=description,
                    read_when="When understanding project scope or metadata.",
                ),
            )
        project_manifest.last_updated = today
        self.save_manifest(project_dir, project_manifest)

        # Update root _index.yaml
        root_manifest = self._load_root_manifest()
        root_manifest.projects = [
            p for p in root_manifest.projects if p.slug != slug
        ]
        root_manifest.projects.append(
            RootManifestEntry(
                slug=slug,
                name=meta.name,
                status=meta.status.value,
                type=meta.type.value,
                description=description,
                created=meta.created,
                updated=meta.updated,
            )
        )
        root_manifest.last_updated = today
        self._save_root_manifest(root_manifest)

        # Update _projects-index.json
        pi = self.load_projects_index()
        pi.projects = [p for p in pi.projects if p.slug != slug]
        pi.projects.append(
            ProjectIndexEntry(
                slug=slug,
                name=meta.name,
                status=meta.status.value,
                type=meta.type.value,
                path=str(project_dir.relative_to(self.root)),
                tags=meta.tags,
                created=meta.created,
                updated=meta.updated,
            )
        )
        self.save_projects_index(pi)

        return project_dir

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def read_file(self, path: str | Path) -> str:
        abs_path = self._safe_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return abs_path.read_text(encoding="utf-8")

    def write_file(
        self,
        path: str | Path,
        content: str,
        description: Optional[str] = None,
        read_when: Optional[str] = None,
    ) -> list[str]:
        """Write a file with all rule enforcement.  Returns list of warnings."""
        abs_path = self._safe_path(path)
        warnings: list[str] = []

        # Block _index.yaml
        if is_manifest(abs_path):
            raise ValueError(
                "_index.yaml is auto-managed. Use update_file_description or update_manifest tools instead."
            )

        # Block append-only files
        if is_append_only(abs_path):
            raise ValueError(
                f"{abs_path.name} is append-only. Use append_to_file instead."
            )

        # Kebab-case enforcement (for new files only)
        expected = to_kebab_case(abs_path.name)
        if abs_path.name != expected and not abs_path.name.startswith("_"):
            raise ValueError(
                f"Filename must be kebab-case. Got {abs_path.name!r}, expected {expected!r}"
            )

        # Knowledge frontmatter check
        rel = self._rel(abs_path)
        if "knowledge" in rel and abs_path.suffix == ".md":
            valid, fm_errors = validate_knowledge_frontmatter(content)
            if not valid:
                warnings.extend(fm_errors)

        # Write file
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")

        # Update refs
        rel_path = self._rel(abs_path)
        self.update_refs_for_file(rel_path, content)

        # Warn on unresolved refs
        parsed = parse_refs(content)
        warnings.extend(self.warn_unresolved_refs(parsed["refs"]))

        # Update manifest
        folder = abs_path.parent
        if not is_manifest(abs_path) and abs_path.suffix in (".md", ".yaml"):
            entry = ManifestEntry(
                name=abs_path.name,
                description=description,
                read_when=read_when,
            )
            self.add_manifest_entry(folder, entry)

        return warnings

    def append_file(self, path: str | Path, content: str) -> list[str]:
        """Append content.  Only allowed for append-only paths."""
        abs_path = self._safe_path(path)
        warnings: list[str] = []

        if is_manifest(abs_path):
            raise ValueError("Cannot append to _index.yaml")

        if not is_append_only(abs_path):
            raise ValueError(
                f"{abs_path.name} is not append-only. Use write_file instead."
            )

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        with abs_path.open("a", encoding="utf-8") as f:
            f.write(content)

        # Update refs on full file
        full_content = abs_path.read_text(encoding="utf-8")
        rel_path = self._rel(abs_path)
        self.update_refs_for_file(rel_path, full_content)
        parsed = parse_refs(content)
        warnings.extend(self.warn_unresolved_refs(parsed["refs"]))

        # For updates/ folders: update last_entry_date instead of marking stale
        if is_updates_folder(abs_path.parent):
            manifest = self.load_manifest(abs_path.parent)
            manifest.last_entry_date = _today()
            manifest.last_updated = _today()
            self.save_manifest(abs_path.parent, manifest)
        else:
            # Mark manifest stale for other append-only files (e.g. decisions.md)
            self.mark_manifest_stale(abs_path.parent)

        return warnings

    def soft_delete(self, path: str | Path) -> str:
        """Move file to _trash/{timestamp}_{filename}."""
        abs_path = self._safe_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        trash_dir = self.root / "_trash"
        trash_dir.mkdir(exist_ok=True)
        dest_name = f"{_now_ts()}_{abs_path.name}"
        dest = trash_dir / dest_name
        shutil.move(str(abs_path), str(dest))

        # Remove from manifest
        folder = abs_path.parent
        manifest = self.load_manifest(folder)
        manifest.files = [f for f in manifest.files if f.name != abs_path.name]
        manifest.last_updated = _today()
        self.save_manifest(folder, manifest)

        # Remove from refs index
        refs_index = self.load_refs_index()
        rel_path = self._rel(abs_path)
        refs_index.entries.pop(rel_path, None)
        self.save_refs_index(refs_index)

        return str(dest.relative_to(self.root))

    def search_files(
        self,
        keyword: str,
        project_slug: Optional[str] = None,
        folder: Optional[str | Path] = None,
    ) -> list[dict[str, Any]]:
        """Search .md files for keyword.  Returns list of {path, line_no, line}.

        ``project_slug`` is the preferred filter (searches projects/{slug}/).
        ``folder`` is a lower-level escape hatch for arbitrary paths.
        """
        if project_slug:
            search_root = self._safe_path(f"projects/{project_slug}")
            if not search_root.is_dir():
                raise FileNotFoundError(f"Project {project_slug!r} not found")
        elif folder:
            search_root = self._safe_path(folder)
        else:
            search_root = self.root
        results: list[dict[str, Any]] = []
        kw_lower = keyword.lower()

        trash_dir = self.root / "_trash"
        for p in sorted(search_root.rglob("*.md")):
            if p.name.startswith("_"):
                continue
            # Skip soft-deleted files that live under _trash/
            if p.is_relative_to(trash_dir):
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, start=1):
                if kw_lower in line.lower():
                    results.append(
                        {
                            "path": self._rel(p),
                            "line_no": i,
                            "line": line.strip(),
                        }
                    )
        return results

    # ------------------------------------------------------------------
    # Ref utilities
    # ------------------------------------------------------------------

    def warn_unresolved_refs(self, refs: list[str]) -> list[str]:
        """Return warning strings for any @refs not found in global index."""
        warnings: list[str] = []
        for ref in refs:
            people_path = self.root / "_global" / "people" / f"{ref}.md"
            company_path = self.root / "_global" / "companies" / f"{ref}.md"
            if not people_path.exists() and not company_path.exists():
                warnings.append(f"Unresolved ref: @{ref} (not found in _global/people or _global/companies)")
        return warnings

    def resolve_ref(self, slug: str) -> tuple[Path, str]:
        """Resolve @slug to (path, content).  Checks people then companies."""
        for sub in ("people", "companies"):
            p = self.root / "_global" / sub / f"{slug}.md"
            if p.exists():
                return p, p.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Ref @{slug} not found in _global/people or _global/companies")

    def get_refs_for(self, ref: str) -> list[str]:
        """Return list of file paths that mention @ref, #tag, or [[link]]."""
        refs_index = self.load_refs_index()
        results: list[str] = []
        for rel_path, entry in refs_index.entries.items():
            if (
                ref in entry.refs
                or ref in entry.tags
                or ref in entry.links
            ):
                results.append(rel_path)
        return results

    # ------------------------------------------------------------------
    # Global entity operations
    # ------------------------------------------------------------------

    def create_person(
        self,
        slug: str,
        name: str,
        extra_fields: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Path:
        folder = self.root / "_global" / "people"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slug}.md"
        if path.exists():
            raise ValueError(f"Person {slug!r} already exists")

        content = PERSON_TEMPLATE.format(name=name)
        if extra_fields:
            for field_name, field_value in extra_fields.items():
                # Replace "**FieldName:** " (trailing space before newline) with value inline
                placeholder = f"**{field_name}:** "
                content = content.replace(placeholder, f"**{field_name}:** {field_value}", 1)

        path.write_text(content, encoding="utf-8")
        self.add_manifest_entry(
            folder,
            ManifestEntry(
                name=f"{slug}.md",
                description=description or f"Person: {name}",
                read_when="When communication or meetings involve this person.",
            ),
        )
        return path

    def create_company(
        self,
        slug: str,
        name: str,
        extra_fields: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Path:
        folder = self.root / "_global" / "companies"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slug}.md"
        if path.exists():
            raise ValueError(f"Company {slug!r} already exists")

        content = COMPANY_TEMPLATE.format(name=name)
        if extra_fields:
            for field_name, field_value in extra_fields.items():
                placeholder = f"**{field_name}:** "
                content = content.replace(placeholder, f"**{field_name}:** {field_value}", 1)
        path.write_text(content, encoding="utf-8")
        self.add_manifest_entry(
            folder,
            ManifestEntry(
                name=f"{slug}.md",
                description=description or f"Company: {name}",
                read_when="When researching this company's context.",
            ),
        )
        return path

    # ------------------------------------------------------------------
    # Global entity listing
    # ------------------------------------------------------------------

    def list_global_people(self) -> list[dict[str, Any]]:
        """Return all entries from _global/people/_index.yaml."""
        folder = self.root / "_global" / "people"
        manifest = self.load_manifest(folder)
        return [e.model_dump() for e in manifest.files]

    def list_global_companies(self) -> list[dict[str, Any]]:
        """Return all entries from _global/companies/_index.yaml."""
        folder = self.root / "_global" / "companies"
        manifest = self.load_manifest(folder)
        return [e.model_dump() for e in manifest.files]

    # ------------------------------------------------------------------
    # Refs index rebuild
    # ------------------------------------------------------------------

    def rebuild_refs_index(self) -> int:
        """Scan all .md files and rebuild _refs-index.json from scratch.

        Returns the number of files indexed.
        """
        new_index = RefsIndex()
        for p in sorted(self.root.rglob("*.md")):
            if p.name.startswith("_"):
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue
            rel_path = self._rel(p)
            parsed = parse_refs(content)
            new_index.entries[rel_path] = RefsIndexEntry(path=rel_path, **parsed)
        self.save_refs_index(new_index)
        return len(new_index.entries)

    # ------------------------------------------------------------------
    # Stale manifest discovery
    # ------------------------------------------------------------------

    def list_stale_manifests(self) -> list[str]:
        """Return relative paths of all folders with stale: true in _index.yaml."""
        stale: list[str] = []
        for p in sorted(self.root.rglob("_index.yaml")):
            # Skip root _index.yaml (different schema)
            if p.parent == self.root:
                continue
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if raw.get("stale", False):
                    stale.append(self._rel(p.parent))
            except Exception:
                pass
        return stale
