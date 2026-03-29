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
    M365Ref,
    ManifestEntry,
    ProjectIndexEntry,
    ProjectMeta,
    ProjectStatus,
    ProjectType,
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
    SYNC_YAML_TEMPLATE,
    UPDATES_MANIFEST_TEMPLATE,
)

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REF_RE = re.compile(r"@([a-z0-9-]+)")
_TAG_RE = re.compile(r"#([a-z0-9-]+)")
_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_M365_REF_RE = re.compile(r"\[(tm|ol|sp):([a-z0-9-]+)(?:/([^\]]*))?\]")


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
    if path.name.lower() == "decisions.md":
        return True
    if (
        len(parts) >= 2
        and parts[-2].lower() == "updates"
        and path.suffix.lower() == ".md"
    ):
        return True
    return False


def is_manifest(path: Path) -> bool:
    """Return True if path is a _index.yaml or _sync.yaml (protected from direct write)."""
    return path.name.lower() in ("_index.yaml", "_sync.yaml")


def is_index_yaml(path: Path) -> bool:
    """Return True if path is a _index.yaml file."""
    return path.name.lower() == "_index.yaml"


def is_sync_yaml(path: Path) -> bool:
    """Return True if path is a _sync.yaml file."""
    return path.name.lower() == "_sync.yaml"


def is_project_people_file(path: Path) -> bool:
    """Return True if path is projects/{slug}/people.md (auto-managed)."""
    if path.name.lower() != "people.md":
        return False
    parts = tuple(p.lower() for p in path.parts)
    return len(parts) >= 3 and parts[-3] == "projects"


def is_updates_folder(folder: Path) -> bool:
    """Return True if folder is an updates/ subdirectory."""
    return folder.name.lower() == "updates"


def _extract_markdown_field(content: str, field_name: str) -> Optional[str]:
    """Extract '**Field:** value' line value; returns None if missing."""
    pattern = re.compile(rf"^\*\*{re.escape(field_name)}:\*\*\s*(.*)$", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return None
    return m.group(1).strip()


def _set_markdown_field(content: str, field_name: str, value: str) -> str:
    """Set or insert a '**Field:** value' line."""
    pattern = re.compile(rf"^\*\*{re.escape(field_name)}:\*\*.*$", re.MULTILINE)
    new_line = f"**{field_name}:** {value}"
    if pattern.search(content):
        return pattern.sub(new_line, content, count=1)
    return re.sub(
        r"^(# .*)$", r"\1\n\n" + new_line, content, count=1, flags=re.MULTILINE
    )


def _extract_projects_from_person(content: str) -> list[str]:
    """Extract project slugs from a person's '## Projects' section (supports [[slug]] and slug bullets)."""
    m = re.search(
        r"^## Projects\s*$([\s\S]*?)(?=^##\s+|\Z)", content, flags=re.MULTILINE
    )
    if not m:
        return []
    section = m.group(1)
    links = re.findall(r"\[\[([a-z0-9-]+)\]\]", section)
    bullets = re.findall(r"^\s*[-*]\s+([a-z0-9-]+)\s*$", section, flags=re.MULTILINE)
    merged = sorted(set(links + bullets))
    return merged


def _render_person_projects_section(project_slugs: list[str]) -> str:
    """Render canonical person projects section body."""
    if not project_slugs:
        return "## Projects\n- (none)\n"
    lines = ["## Projects"]
    for slug in sorted(set(project_slugs)):
        lines.append(f"- [[{slug}]]")
    return "\n".join(lines) + "\n"


def _replace_person_projects_section(content: str, project_slugs: list[str]) -> str:
    """Replace or append canonical '## Projects' section in a person file."""
    replacement = _render_person_projects_section(project_slugs)
    pattern = re.compile(r"^## Projects\s*$[\s\S]*?(?=^##\s+|\Z)", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(replacement, content, count=1)
    return content.rstrip() + "\n\n" + replacement


def _get_markdown_section_body(content: str, heading: str) -> Optional[str]:
    """Return section body for a level-2 heading (without heading line), or None."""
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        re.MULTILINE,
    )
    m = pattern.search(content)
    if not m:
        return None
    return m.group(1)


def _replace_markdown_section(content: str, heading: str, body: str) -> str:
    """Replace or append a level-2 section with exact body content."""
    replacement = f"## {heading}\n{body.rstrip()}\n"
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$[\s\S]*?(?=^##\s+|\Z)",
        re.MULTILINE,
    )
    if pattern.search(content):
        return pattern.sub(replacement, content, count=1)
    return content.rstrip() + "\n\n" + replacement


def parse_refs(content: str) -> dict[str, Any]:
    """Parse @refs, #tags, [[links]], and [m365:] tokens from markdown content."""
    refs = list(set(_REF_RE.findall(content)))
    tags = list(set(_TAG_RE.findall(content)))
    links = list(set(_LINK_RE.findall(content)))
    m365_refs: list[M365Ref] = []
    seen_m365: set[str] = set()
    for m in _M365_REF_RE.finditer(content):
        try:
            ref_type = m.group(1)
            source_id = m.group(2)
            remainder = m.group(3) or None
            key = f"{ref_type}:{source_id}:{remainder}"
            if key in seen_m365:
                continue
            seen_m365.add(key)
            if ref_type == "sp":
                m365_refs.append(M365Ref(type=ref_type, source_id=source_id, path=remainder))
            else:
                m365_refs.append(M365Ref(type=ref_type, source_id=source_id, message_id=remainder))
        except Exception:
            continue
    return {"refs": refs, "tags": tags, "links": links, "m365_refs": m365_refs}


def validate_knowledge_frontmatter(content: str) -> tuple[bool, list[str]]:
    """Validate that knowledge entry starts with valid YAML frontmatter."""
    errors: list[str] = []
    if not content.startswith("---"):
        errors.append(
            "Knowledge entries must start with a YAML frontmatter block (---)"
        )
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

        # Windows case-insensitivity: compare lower-case strings
        if not str(resolved).lower().startswith(str(self.root).lower()):
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
            pi_path.write_text(json.dumps({"projects": []}, indent=2), encoding="utf-8")

        # _refs-index.json
        ri_path = self.root / "_refs-index.json"
        if not ri_path.exists():
            ri_path.write_text(json.dumps({"entries": {}}, indent=2), encoding="utf-8")

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
        path.write_text(json.dumps(index.model_dump(), indent=2), encoding="utf-8")

    def load_refs_index(self) -> RefsIndex:
        path = self.root / "_refs-index.json"
        if not path.exists():
            return RefsIndex()
        data = json.loads(path.read_text(encoding="utf-8"))
        # Lazy migration: add m365_refs: [] to entries that lack it
        for entry_data in data.get("entries", {}).values():
            entry_data.setdefault("m365_refs", [])
        return RefsIndex(**data)

    def save_refs_index(self, index: RefsIndex) -> None:
        path = self.root / "_refs-index.json"
        path.write_text(json.dumps(index.model_dump(), indent=2), encoding="utf-8")

    def update_refs_for_file(self, rel_path: str, content: str) -> None:
        """Parse content for refs/tags/links/m365_refs and update _refs-index.json."""
        parsed = parse_refs(content)
        refs_index = self.load_refs_index()
        existing = refs_index.entries.get(rel_path)
        m365_refs = parsed.get("m365_refs", [])
        refs_index.entries[rel_path] = RefsIndexEntry(
            path=rel_path,
            refs=parsed["refs"],
            tags=parsed["tags"],
            links=parsed["links"],
            m365_refs=m365_refs,
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
        # Replace if entry with same name (case-insensitive on Windows if needed, but we keep the object casing)
        manifest.files = [
            f for f in manifest.files if f.name.lower() != entry.name.lower()
        ]
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

        # Map existing descriptions/metadata by case-insensitive filename
        existing_meta = {e.name.lower(): e for e in manifest.files}

        # Standard description for updates folders if missing
        if is_updates_folder(folder) and not manifest.description:
            manifest.description = (
                "Chronological update log. Read the file directly for recent entries."
            )

        # Re-scan folder and build fresh list
        new_files: list[ManifestEntry] = []
        for p in sorted(folder.iterdir()):
            # Only index specific extensions, skip files starting with _ (including _index.yaml)
            if (
                p.is_file()
                and p.suffix.lower() in (".md", ".yaml", ".json")
                and not p.name.startswith("_")
            ):
                name_low = p.name.lower()
                if name_low in existing_meta:
                    # Keep existing entry (preserves custom descriptions)
                    new_files.append(existing_meta[name_low])
                else:
                    # New entry
                    new_files.append(ManifestEntry(name=p.name))

        manifest.files = new_files
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
        correspondence_dir = project_dir / "correspondence"
        correspondence_manifest = self.load_manifest(correspondence_dir)
        for fname in ("email-threads.md", "calls.md", "messages.md"):
            (correspondence_dir / fname).write_text(
                f"# {fname.replace('-', ' ').title()} — {meta.name}\n\n",
                encoding="utf-8",
            )
            correspondence_manifest.files.append(
                ManifestEntry(
                    name=fname,
                    description=f"Chronological {fname.replace('.md', '').replace('-', ' ')} log for {meta.name}.",
                )
            )
        correspondence_manifest.last_updated = today
        self.save_manifest(correspondence_dir, correspondence_manifest)

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

        # Keep project people.md auto-managed from global person-project relationships.
        self._ensure_project_people_sync(slug)

        # Update root _index.yaml
        root_manifest = self._load_root_manifest()
        root_manifest.projects = [p for p in root_manifest.projects if p.slug != slug]
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

    def update_project(
        self,
        slug: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> ProjectMeta:
        project_dir = self.root / "projects" / slug
        if not project_dir.exists():
            raise FileNotFoundError(f"Project {slug!r} not found")

        meta_path = project_dir / "_meta.yaml"
        if not meta_path.exists():
            raise FileNotFoundError(f"_meta.yaml missing for project {slug!r}")

        raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

        if name is not None:
            raw["name"] = name
        if status is not None:
            raw["status"] = ProjectStatus(status).value
        if type is not None:
            raw["type"] = ProjectType(type).value

        if meta is not None:
            if "company" in meta:
                raw["company"] = meta["company"]
            if "owner" in meta:
                raw["owner"] = meta["owner"]
            if "team" in meta:
                raw["team"] = meta["team"]
            if "tags" in meta:
                raw["tags"] = meta["tags"]

        raw["updated"] = _today()

        meta_content = PROJECT_META_TEMPLATE.format(**raw)
        meta_path.write_text(meta_content, encoding="utf-8")

        root_manifest = self._load_root_manifest()
        for p in root_manifest.projects:
            if p.slug == slug:
                if name is not None:
                    p.name = name
                if status is not None:
                    p.status = raw["status"]
                if type is not None:
                    p.type = raw["type"]
                p.updated = raw["updated"]
                break
        root_manifest.last_updated = _today()
        self._save_root_manifest(root_manifest)

        pi = self.load_projects_index()
        for p in pi.projects:
            if p.slug == slug:
                if name is not None:
                    p.name = name
                if status is not None:
                    p.status = raw["status"]
                if type is not None:
                    p.type = raw["type"]
                if "tags" in raw:
                    p.tags = raw.get("tags", [])
                p.updated = raw["updated"]
                break
        self.save_projects_index(pi)

        return ProjectMeta(**raw)

    def delete_project(self, slug: str) -> str:
        project_dir = self.root / "projects" / slug
        if not project_dir.exists():
            raise FileNotFoundError(f"Project {slug!r} not found")

        trash_dir = self.root / "_trash"
        trash_dir.mkdir(exist_ok=True)
        dest_name = f"{_now_ts()}_project_{slug}"
        dest = trash_dir / dest_name
        shutil.move(str(project_dir), str(dest))

        root_manifest = self._load_root_manifest()
        root_manifest.projects = [p for p in root_manifest.projects if p.slug != slug]
        root_manifest.last_updated = _today()
        self._save_root_manifest(root_manifest)

        pi = self.load_projects_index()
        pi.projects = [p for p in pi.projects if p.slug != slug]
        self.save_projects_index(pi)

        refs_index = self.load_refs_index()
        prefix = f"projects/{slug}/"
        keys_to_remove = [k for k in refs_index.entries.keys() if k.startswith(prefix)]
        for k in keys_to_remove:
            del refs_index.entries[k]
        self.save_refs_index(refs_index)

        return str(dest.relative_to(self.root))

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
        if abs_path.name.lower() == "_index.yaml":
            raise ValueError(
                "_index.yaml is auto-managed. Use update_file_description or update_manifest tools instead."
            )

        # Block _sync.yaml
        if is_sync_yaml(abs_path):
            raise ValueError(
                "_sync.yaml is auto-managed. Use get_sync_state, update_sync_state, or add_sync_source tools instead."
            )

        # Block project people.md (auto-managed from global person relationships)
        rel = self._rel(abs_path)
        if is_project_people_file(Path(rel)):
            raise ValueError(
                "projects/{slug}/people.md is auto-managed. Use link_person_to_project or unlink_person_from_project instead."
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
        if "knowledge" in rel and abs_path.suffix.lower() == ".md":
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
        if not is_manifest(abs_path) and abs_path.suffix.lower() in (
            ".md",
            ".yaml",
            ".json",
        ):
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

        # Force a manifest rebuild for this folder to ensure new file is indexed
        self.rebuild_manifest(abs_path.parent)

        # Defensive fallback: guarantee the appended file is present in manifest.
        # This protects against rare manifest desync scenarios on append-only flows.
        manifest = self.load_manifest(abs_path.parent)
        if not any(f.name.lower() == abs_path.name.lower() for f in manifest.files):
            manifest.files.append(ManifestEntry(name=abs_path.name))
            manifest.last_updated = _today()
            self.save_manifest(abs_path.parent, manifest)

        # For updates/ folders: ensure last_entry_date is set to today
        if is_updates_folder(abs_path.parent):
            manifest = self.load_manifest(abs_path.parent)
            manifest.last_entry_date = _today()
            self.save_manifest(abs_path.parent, manifest)
        else:
            # Non-updates append-only files (currently decisions.md) stale the folder manifest.
            self.mark_manifest_stale(abs_path.parent)

        return warnings

    def soft_delete(self, path: str | Path) -> str:
        """Move file to _trash/{timestamp}_{filename}."""
        abs_path = self._safe_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        rel = self._rel(abs_path)
        if is_project_people_file(Path(rel)):
            raise ValueError(
                "projects/{slug}/people.md is auto-managed and cannot be deleted."
            )

        if is_sync_yaml(abs_path):
            raise ValueError(
                "_sync.yaml cannot be deleted via the MCP interface. "
                "To remove M365 config, use add_sync_source with enabled=false."
            )

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
                warnings.append(
                    f"Unresolved ref: @{ref} (not found in _global/people or _global/companies)"
                )
        return warnings

    def resolve_ref(self, slug: str) -> tuple[Path, str]:
        """Resolve @slug to (path, content).  Checks people then companies."""
        for sub in ("people", "companies"):
            p = self.root / "_global" / sub / f"{slug}.md"
            if p.exists():
                return p, p.read_text(encoding="utf-8")
        raise FileNotFoundError(
            f"Ref @{slug} not found in _global/people or _global/companies"
        )

    def get_refs_for(self, ref: str) -> list[str]:
        """Return list of file paths that mention @ref, #tag, [[link]], or m365 source_id."""
        refs_index = self.load_refs_index()
        results: list[str] = []
        for rel_path, entry in refs_index.entries.items():
            if ref in entry.refs or ref in entry.tags or ref in entry.links:
                results.append(rel_path)
                continue
            # Also check m365_refs source_id
            if any(m.source_id == ref for m in entry.m365_refs):
                results.append(rel_path)
        return results

    # ------------------------------------------------------------------
    # Global entity operations
    # ------------------------------------------------------------------

    def _get_person_path(self, slug: str) -> Path:
        return self.root / "_global" / "people" / f"{slug}.md"

    def _get_person_company(self, person_content: str) -> str:
        company = _extract_markdown_field(person_content, "Company")
        if not company:
            return "Other"
        return company

    def _ensure_project_people_sync(self, project_slug: str) -> Path:
        """Regenerate projects/{slug}/people.md from global people linked to the project."""
        project_dir = self.root / "projects" / project_slug
        if not project_dir.exists():
            raise FileNotFoundError(f"Project {project_slug!r} not found")

        people_folder = self.root / "_global" / "people"
        grouped: dict[str, list[tuple[str, str]]] = {}

        if people_folder.exists():
            for p in sorted(people_folder.glob("*.md")):
                slug = p.stem
                content = p.read_text(encoding="utf-8")
                projects = _extract_projects_from_person(content)
                if project_slug not in projects:
                    continue
                name = content.splitlines()[0].lstrip("# ").strip() if content else slug
                company = self._get_person_company(content) or "Other"
                grouped.setdefault(company, []).append((slug, name))

        lines = [
            f"# People - {project_slug}",
            "",
            "> Auto-managed from global person-project relationships.",
            "",
        ]
        if not grouped:
            lines.append("_(no linked people yet)_")
        else:
            for company in sorted(grouped.keys(), key=lambda x: x.lower()):
                lines.append(f"## {company}")
                for slug, name in sorted(grouped[company], key=lambda x: x[1].lower()):
                    lines.append(f"- **@{slug}**: {name}")
                lines.append("")

        people_path = project_dir / "people.md"
        people_content = "\n".join(lines).rstrip() + "\n"
        people_path.write_text(people_content, encoding="utf-8")
        self.update_refs_for_file(self._rel(people_path), people_content)

        self.add_manifest_entry(
            project_dir,
            ManifestEntry(
                name="people.md",
                description=f"Auto-managed project people grouped by company for {project_slug}.",
                read_when="Before communication; global person profiles remain source of truth.",
            ),
        )
        return people_path

    def link_person_to_project(
        self, person_slug: str, project_slug: str
    ) -> tuple[Path, Path]:
        """Create person-project relation and sync both global person + project people.md."""
        person_path = self._get_person_path(person_slug)
        if not person_path.exists():
            raise FileNotFoundError(f"Person {person_slug!r} not found")

        project_dir = self.root / "projects" / project_slug
        if not project_dir.exists():
            raise FileNotFoundError(f"Project {project_slug!r} not found")

        content = person_path.read_text(encoding="utf-8")
        projects = _extract_projects_from_person(content)
        projects = sorted(set(projects + [project_slug]))
        content = _replace_person_projects_section(content, projects)
        person_path.write_text(content, encoding="utf-8")

        project_people_path = self._ensure_project_people_sync(project_slug)
        return person_path, project_people_path

    def unlink_person_from_project(
        self, person_slug: str, project_slug: str
    ) -> tuple[Path, Path]:
        """Remove person-project relation and sync both global person + project people.md."""
        person_path = self._get_person_path(person_slug)
        if not person_path.exists():
            raise FileNotFoundError(f"Person {person_slug!r} not found")

        project_dir = self.root / "projects" / project_slug
        if not project_dir.exists():
            raise FileNotFoundError(f"Project {project_slug!r} not found")

        content = person_path.read_text(encoding="utf-8")
        projects = [
            p for p in _extract_projects_from_person(content) if p != project_slug
        ]
        content = _replace_person_projects_section(content, projects)
        person_path.write_text(content, encoding="utf-8")

        project_people_path = self._ensure_project_people_sync(project_slug)
        return person_path, project_people_path

    def edit_person_notes(
        self,
        slug: str,
        notes: str,
        mode: str = "append",
    ) -> tuple[Path, list[str]]:
        """Edit manual notes section on a global person profile.

        mode:
          - append: append notes to existing section body
          - replace: replace section body with notes
        """
        if mode not in {"append", "replace"}:
            raise ValueError("mode must be 'append' or 'replace'")

        path = self._get_person_path(slug)
        if not path.exists():
            raise FileNotFoundError(f"Person {slug!r} not found")

        content = path.read_text(encoding="utf-8")
        existing_body = _get_markdown_section_body(content, "Notes")
        if existing_body is None:
            existing_body = "\n_(manual notes empty)_\n"

        if mode == "append":
            base = existing_body.rstrip()
            if base == "_(manual notes empty)_":
                base = ""
            if base:
                new_body = f"{base}\n\n{notes.strip()}\n"
            else:
                new_body = f"{notes.strip()}\n"
        else:
            new_body = f"{notes.strip()}\n"

        content = _replace_markdown_section(content, "Notes", new_body)
        path.write_text(content, encoding="utf-8")

        rel_path = self._rel(path)
        self.update_refs_for_file(rel_path, content)

        parsed = parse_refs(notes)
        warnings = self.warn_unresolved_refs(parsed["refs"])
        return path, warnings

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
        company_value = "Other"
        if extra_fields:
            for field_name, field_value in extra_fields.items():
                value_str = "" if field_value is None else str(field_value)
                content = _set_markdown_field(content, field_name, value_str)
                if field_name.lower() == "company" and value_str.strip():
                    company_value = value_str.strip()
        content = _set_markdown_field(content, "Company", company_value)

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
                content = content.replace(
                    placeholder, f"**{field_name}:** {field_value}", 1
                )
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

    def update_person(
        self,
        slug: str,
        name: Optional[str] = None,
        extra_fields: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Path:
        folder = self.root / "_global" / "people"
        path = folder / f"{slug}.md"
        if not path.exists():
            raise FileNotFoundError(f"Person {slug!r} not found")

        content = path.read_text(encoding="utf-8")

        if name is not None:
            content = re.sub(
                r"^# .*", f"# {name}", content, count=1, flags=re.MULTILINE
            )

        if extra_fields:
            for field_name, field_value in extra_fields.items():
                value_str = "" if field_value is None else str(field_value)
                if field_name.lower() == "company" and not value_str.strip():
                    value_str = "Other"
                content = _set_markdown_field(content, field_name, value_str)

        # Keep Projects section canonical and preserve existing links.
        existing_projects = _extract_projects_from_person(content)
        content = _replace_person_projects_section(content, existing_projects)

        path.write_text(content, encoding="utf-8")

        if description is not None:
            self.update_manifest_entry(folder, f"{slug}.md", description=description)

        # If this person belongs to projects, refresh their project people.md grouping.
        for project_slug in existing_projects:
            project_dir = self.root / "projects" / project_slug
            if project_dir.exists():
                self._ensure_project_people_sync(project_slug)

        return path

    def update_company(
        self,
        slug: str,
        name: Optional[str] = None,
        extra_fields: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Path:
        folder = self.root / "_global" / "companies"
        path = folder / f"{slug}.md"
        if not path.exists():
            raise FileNotFoundError(f"Company {slug!r} not found")

        content = path.read_text(encoding="utf-8")

        if name is not None:
            content = re.sub(
                r"^# .*", f"# {name}", content, count=1, flags=re.MULTILINE
            )

        if extra_fields:
            for field_name, field_value in extra_fields.items():
                placeholder_pattern = rf"^\*\*{field_name}:\*\*.*$"
                new_line = f"**{field_name}:** {field_value}"

                if re.search(placeholder_pattern, content, flags=re.MULTILINE):
                    content = re.sub(
                        placeholder_pattern,
                        new_line,
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                else:
                    content = re.sub(
                        r"^(# .*)$",
                        r"\1\n\n" + new_line,
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )

        path.write_text(content, encoding="utf-8")

        if description is not None:
            self.update_manifest_entry(folder, f"{slug}.md", description=description)

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
            m365_refs = parsed.get("m365_refs", [])
            new_index.entries[rel_path] = RefsIndexEntry(
                path=rel_path,
                refs=parsed["refs"],
                tags=parsed["tags"],
                links=parsed["links"],
                m365_refs=m365_refs,
            )
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

    # ------------------------------------------------------------------
    # Sync state (_sync.yaml) management
    # ------------------------------------------------------------------

    def _sync_yaml_path(self, project_slug: str) -> Path:
        return self.root / "projects" / project_slug / "_sync.yaml"

    def _load_sync_state_raw(self, project_slug: str) -> Optional[dict[str, Any]]:
        """Load _sync.yaml as a raw dict, or None if it does not exist."""
        p = self._sync_yaml_path(project_slug)
        if not p.exists():
            return None
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _save_sync_state_raw(self, project_slug: str, data: dict[str, Any]) -> None:
        """Write _sync.yaml atomically."""
        p = self._sync_yaml_path(project_slug)
        header = (
            "# Auto-managed by sync pipeline. Do not edit manually.\n"
            "# Missing file = no M365 sources configured for this project. Not an error.\n\n"
        )
        p.write_text(
            header + yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _minimal_sync_state(self) -> dict[str, Any]:
        """Return a minimal valid _sync.yaml dict structure."""
        return {
            "last_sync": None,
            "sources": {"teams": [], "outlook": [], "sharepoint": []},
            "pipeline": {
                "correspondence_frequency": "daily",
                "knowledge_frequency": "weekly",
                "last_knowledge_synthesis": None,
                "next_knowledge_synthesis": None,
            },
        }

    def get_sync_state(self, project_slug: str) -> dict[str, Any]:
        """Read _sync.yaml for a project.

        Returns full content as dict, or {"result": null, "warnings": [...]} if missing.
        """
        raw = self._load_sync_state_raw(project_slug)
        if raw is None:
            return {"result": None, "warnings": ["No sync state found"]}
        return {"result": raw, "warnings": []}

    def update_sync_state(
        self,
        project_slug: str,
        source_type: str,
        source_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update watermark fields for a specific source or pipeline config.

        source_type: "teams" | "outlook" | "sharepoint" | "pipeline"
        Returns the updated entry.
        """
        raw = self._load_sync_state_raw(project_slug)
        if raw is None:
            raw = self._minimal_sync_state()

        _ALLOWED_SOURCE_FIELDS = {
            "last_processed_at", "last_message_id", "last_modified_etag",
            "unprocessed_count", "enabled",
        }
        _ALLOWED_PIPELINE_FIELDS = {
            "last_knowledge_synthesis", "next_knowledge_synthesis",
            "correspondence_frequency", "knowledge_frequency",
        }

        if source_type == "pipeline":
            pipeline = raw.setdefault("pipeline", {})
            for k, v in fields.items():
                if k == "last_sync":
                    raw["last_sync"] = v
                elif k in _ALLOWED_PIPELINE_FIELDS:
                    pipeline[k] = v
                else:
                    raise ValueError(f"Field {k!r} is not allowed on pipeline config")
            self._save_sync_state_raw(project_slug, raw)
            return {"result": pipeline, "warnings": []}

        valid_types = ("teams", "outlook", "sharepoint")
        if source_type not in valid_types:
            raise ValueError(f"source_type must be one of {valid_types}")

        sources = raw.setdefault("sources", {})
        source_list: list[dict[str, Any]] = sources.setdefault(source_type, [])

        target = next((s for s in source_list if s.get("id") == source_id), None)
        if target is None:
            raise ValueError(
                f"Source {source_id!r} not found in {source_type} sources for project {project_slug!r}. "
                "Use add_sync_source to register new sources."
            )

        for k, v in fields.items():
            if k not in _ALLOWED_SOURCE_FIELDS:
                raise ValueError(f"Field {k!r} is not allowed on source entries")
            target[k] = v

        self._save_sync_state_raw(project_slug, raw)
        return {"result": target, "warnings": []}

    def add_sync_source(
        self,
        project_slug: str,
        source_type: str,
        id: str,
        label: str,
        enabled: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Register a new M365 source for a project.

        Validates kebab-case id uniqueness; creates _sync.yaml if missing.
        """
        valid_types = ("teams", "outlook", "sharepoint")
        if source_type not in valid_types:
            raise ValueError(f"source_type must be one of {valid_types}")

        if not _KEBAB_RE.match(id):
            raise ValueError(
                f"id must be kebab-case (lowercase letters, digits, hyphens). Got: {id!r}"
            )

        raw = self._load_sync_state_raw(project_slug)
        if raw is None:
            raw = self._minimal_sync_state()

        sources = raw.setdefault("sources", {})
        source_list: list[dict[str, Any]] = sources.setdefault(source_type, [])

        if any(s.get("id") == id for s in source_list):
            raise ValueError(
                f"Source id {id!r} already exists in {source_type} sources for project {project_slug!r}"
            )

        new_source: dict[str, Any] = {
            "id": id,
            "label": label,
            "last_processed_at": None,
            "last_message_id": None,
            "unprocessed_count": 0,
            "enabled": enabled,
        }

        if source_type == "teams":
            channel_id = kwargs.get("channel_id")
            if not channel_id:
                raise ValueError("channel_id is required for teams sources")
            new_source["channel_id"] = channel_id

        elif source_type == "outlook":
            folder_id = kwargs.get("folder_id")
            if not folder_id:
                raise ValueError("folder_id is required for outlook sources")
            new_source["folder_id"] = folder_id

        elif source_type == "sharepoint":
            site_url = kwargs.get("site_url")
            library = kwargs.get("library")
            if not site_url:
                raise ValueError("site_url is required for sharepoint sources")
            if not library:
                raise ValueError("library is required for sharepoint sources")
            new_source["site_url"] = site_url
            new_source["library"] = library
            new_source["last_modified_etag"] = None

        source_list.append(new_source)
        self._save_sync_state_raw(project_slug, raw)
        return {"result": new_source, "warnings": []}

    def list_projects_due_for_sync(
        self, frequency: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Return projects where a sync run is overdue.

        frequency: "daily" | "weekly" | None (all overdue)
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        today_cutoff = now.replace(hour=6, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)

        results: list[dict[str, Any]] = []
        pi = self.load_projects_index()

        for project in pi.projects:
            slug = project.slug
            raw = self._load_sync_state_raw(slug)
            if raw is None:
                continue

            pipeline = raw.get("pipeline", {})
            correspondence_freq = pipeline.get("correspondence_frequency", "daily")

            sources_dict = raw.get("sources", {})
            overdue_sources: list[dict[str, Any]] = []

            for src_type, src_list in sources_dict.items():
                if not isinstance(src_list, list):
                    continue
                for source in src_list:
                    if not source.get("enabled", True):
                        continue

                    # Determine the effective frequency for this source
                    effective_freq = correspondence_freq
                    if frequency is not None and effective_freq != frequency:
                        continue
                    if effective_freq == "manual":
                        continue

                    last_processed = source.get("last_processed_at")
                    is_overdue = False

                    if last_processed is None:
                        is_overdue = True
                    else:
                        try:
                            last_dt = datetime.fromisoformat(
                                last_processed.replace("Z", "+00:00")
                            )
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            if effective_freq == "daily":
                                is_overdue = last_dt < today_cutoff
                            elif effective_freq == "weekly":
                                is_overdue = last_dt < seven_days_ago
                        except Exception:
                            is_overdue = True

                    if is_overdue:
                        overdue_sources.append({
                            "id": source.get("id"),
                            "type": src_type,
                            "label": source.get("label"),
                            "last_processed_at": last_processed,
                        })

            if overdue_sources:
                results.append({
                    "slug": slug,
                    "name": project.name,
                    "overdue_sources": overdue_sources,
                })

        return results

    def list_projects_due_for_synthesis(self) -> list[dict[str, Any]]:
        """Return projects where a knowledge synthesis run is overdue."""
        today = date.today().isoformat()
        results: list[dict[str, Any]] = []
        pi = self.load_projects_index()

        for project in pi.projects:
            slug = project.slug
            raw = self._load_sync_state_raw(slug)
            if raw is None:
                continue

            pipeline = raw.get("pipeline", {})
            next_synthesis = pipeline.get("next_knowledge_synthesis")
            if not next_synthesis:
                continue

            if next_synthesis <= today:
                results.append({
                    "slug": slug,
                    "name": project.name,
                    "last_knowledge_synthesis": pipeline.get("last_knowledge_synthesis"),
                    "next_knowledge_synthesis": next_synthesis,
                })

        return results

    def resolve_m365_ref(
        self, project_slug: str, ref: str
    ) -> dict[str, Any]:
        """Resolve an M365 reference token to its full metadata.

        Never calls M365 directly — returns local metadata only.
        """
        # Strip leading/trailing brackets if present
        clean = ref.strip().lstrip("[").rstrip("]")

        m = re.match(r"^(tm|ol|sp):([a-z0-9-]+)(?:/(.+))?$", clean)
        if not m:
            return {"error": f"Cannot parse M365 ref: {ref!r}"}

        ref_type = m.group(1)
        source_id = m.group(2)
        path_part = m.group(3) or None

        raw = self._load_sync_state_raw(project_slug)
        if raw is None:
            return {"error": f"No M365 sources configured for project {project_slug!r}"}

        type_map = {"tm": "teams", "ol": "outlook", "sp": "sharepoint"}
        source_type = type_map.get(ref_type, ref_type)

        sources_dict = raw.get("sources", {})
        source_list = sources_dict.get(source_type, [])
        source = next((s for s in source_list if s.get("id") == source_id), None)

        if source is None:
            return {
                "error": f"Source {source_id!r} not registered for project {project_slug!r}"
            }

        # Check for local doc copy (sp refs only)
        local_doc: Optional[str] = None
        if ref_type == "sp" and path_part:
            filename = Path(path_part).name
            docs_dir = self.root / "projects" / project_slug / "docs"
            if docs_dir.is_dir():
                for candidate in docs_dir.rglob(filename):
                    local_doc = self._rel(candidate)
                    break

        # Check for knowledge entry referencing this source
        knowledge_entry: Optional[str] = None
        refs_index = self.load_refs_index()
        for entry_path, entry in refs_index.entries.items():
            if not entry_path.startswith(f"projects/{project_slug}/knowledge/"):
                continue
            if any(m_ref.source_id == source_id for m_ref in entry.m365_refs):
                knowledge_entry = entry_path
                break

        result: dict[str, Any] = {
            "source_id": source_id,
            "type": source_type,
            "label": source.get("label"),
            "last_processed_at": source.get("last_processed_at"),
            "local_doc": local_doc,
            "knowledge_entry": knowledge_entry,
            "m365_available": False,
        }

        if ref_type == "sp":
            result["site_url"] = source.get("site_url")
            result["library"] = source.get("library")
            result["path"] = path_part
        elif ref_type == "tm":
            result["channel_id"] = source.get("channel_id")
            result["message_id"] = path_part
        elif ref_type == "ol":
            result["folder_id"] = source.get("folder_id")
            result["message_id"] = path_part

        return result
