"""Data models for the Project Memory MCP server."""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, field_validator, model_validator


class ProjectStatus(str, Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class ProjectType(str, Enum):
    client = "client"
    internal = "internal"
    research = "research"
    personal = "personal"


class ProjectMeta(BaseModel):
    """Represents _meta.yaml for a project."""

    id: str
    slug: str
    name: str
    status: ProjectStatus = ProjectStatus.active
    type: ProjectType = ProjectType.internal
    company: Optional[str] = None
    owner: Optional[str] = None
    team: list[str] = []
    tags: list[str] = []
    created: str
    updated: str

    @field_validator("created", "updated")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date must be YYYY-MM-DD format, got: {v!r}")
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid date: {v!r}")
        return v


class KnowledgeFrontmatter(BaseModel):
    """Frontmatter for knowledge/ entries."""

    source: Optional[Union[str, List[str]]] = None
    processed: Optional[str] = None
    method: Optional[str] = None
    model: Optional[str] = None
    prompt_ref: Optional[str] = None

    @field_validator("processed")
    @classmethod
    def validate_processed(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"processed must be YYYY-MM-DD format, got: {v!r}")
        return v


class ManifestEntry(BaseModel):
    """A single file entry in _index.yaml."""

    name: str
    description: Optional[str] = None
    read_when: Optional[str] = None
    stale_after: Optional[str] = None


class FolderManifest(BaseModel):
    """Represents the full _index.yaml for a folder."""

    last_updated: str
    stale: bool = False
    description: Optional[str] = None
    last_entry_date: Optional[str] = None
    files: list[ManifestEntry] = []

    @field_validator("last_updated")
    @classmethod
    def validate_last_updated(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"last_updated must be YYYY-MM-DD, got: {v!r}")
        return v


class RootManifestEntry(BaseModel):
    """Project summary entry in root _index.yaml."""

    slug: str
    name: str
    status: str = "active"
    type: str = "internal"
    description: Optional[str] = None
    created: str
    updated: str


class RootManifest(BaseModel):
    """Root _index.yaml listing all projects."""

    last_updated: str
    projects: list[RootManifestEntry] = []


class ProjectIndexEntry(BaseModel):
    """Single entry in _projects-index.json."""

    slug: str
    name: str
    status: str = "active"
    type: str = "internal"
    path: str
    tags: list[str] = []
    created: str
    updated: str


class ProjectsIndex(BaseModel):
    """Represents _projects-index.json."""

    projects: list[ProjectIndexEntry] = []


class M365Ref(BaseModel):
    """A parsed M365 reference token ([tm:], [ol:], [sp:])."""

    type: str  # "tm", "ol", or "sp"
    source_id: str
    path: Optional[str] = None  # for sp refs (everything after first /)
    message_id: Optional[str] = None  # for tm/ol refs (everything after first /)


class InternalRef(BaseModel):
    """A parsed internal cross-reference token ([mem:path/to/file.md])."""

    path: str  # root-relative path to the referenced file


class RefsIndexEntry(BaseModel):
    """Per-file refs entry in _refs-index.json."""

    path: str
    refs: list[str] = []
    tags: list[str] = []
    links: list[str] = []
    m365_refs: list[M365Ref] = []
    internal_refs: list[InternalRef] = []


class RefsIndex(BaseModel):
    """Represents _refs-index.json."""

    entries: dict[str, RefsIndexEntry] = {}


# ---------------------------------------------------------------------------
# Sync state models (_sync.yaml)
# ---------------------------------------------------------------------------


class SyncSourceBase(BaseModel):
    """Common fields for all M365 sync sources."""

    id: str
    label: str
    last_processed_at: Optional[str] = None
    last_message_id: Optional[str] = None
    unprocessed_count: int = 0
    enabled: bool = True


class TeamsSyncSource(SyncSourceBase):
    """Teams channel sync source."""

    channel_id: str


class OutlookSyncSource(SyncSourceBase):
    """Outlook folder/thread sync source."""

    folder_id: str


class SharePointSyncSource(SyncSourceBase):
    """SharePoint document library sync source."""

    site_url: str
    library: str
    last_modified_etag: Optional[str] = None


class SyncPipeline(BaseModel):
    """Pipeline scheduling configuration in _sync.yaml."""

    correspondence_frequency: str = "daily"  # daily | weekly | manual
    knowledge_frequency: str = "weekly"  # daily | weekly | manual
    last_knowledge_synthesis: Optional[str] = None  # YYYY-MM-DD
    next_knowledge_synthesis: Optional[str] = None  # YYYY-MM-DD


class SyncSources(BaseModel):
    """Source lists grouped by type in _sync.yaml."""

    teams: list[Any] = []
    outlook: list[Any] = []
    sharepoint: list[Any] = []


class SyncState(BaseModel):
    """Represents projects/{slug}/_sync.yaml."""

    last_sync: Optional[str] = None
    sources: SyncSources = SyncSources()
    pipeline: SyncPipeline = SyncPipeline()
