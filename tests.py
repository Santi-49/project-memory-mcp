"""Tests for the Project Memory MCP server."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from filesystem import (
    MemoryFS,
    is_append_only,
    is_manifest,
    parse_refs,
    to_kebab_case,
    validate_knowledge_frontmatter,
)
from models import (
    FolderManifest,
    ManifestEntry,
    ProjectMeta,
    ProjectStatus,
    ProjectType,
)
from server import create_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = "2025-01-15"


def make_meta(slug: str = "test-proj", name: str = "Test Project") -> ProjectMeta:
    return ProjectMeta(
        id="test-id",
        slug=slug,
        name=name,
        status=ProjectStatus.active,
        type=ProjectType.internal,
        created=TODAY,
        updated=TODAY,
    )


def parse_result(tool_result) -> dict:
    return json.loads(tool_result.content[0].text)


# ---------------------------------------------------------------------------
# Unit tests — filesystem helpers
# ---------------------------------------------------------------------------


class TestToKebabCase:
    def test_simple(self):
        assert to_kebab_case("hello-world.md") == "hello-world.md"

    def test_spaces(self):
        assert to_kebab_case("My File.md") == "my-file.md"

    def test_underscores(self):
        assert to_kebab_case("my_file.md") == "my-file.md"

    def test_uppercase(self):
        assert to_kebab_case("MyFile.md") == "myfile.md"

    def test_no_extension(self):
        assert to_kebab_case("my-slug") == "my-slug"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            to_kebab_case("!!!")


class TestIsAppendOnly:
    def test_decisions(self):
        assert is_append_only(Path("projects/my-proj/decisions.md"))

    def test_updates_md(self):
        assert is_append_only(Path("projects/my-proj/updates/2025-01-15.md"))

    def test_updates_subdir_only_md(self):
        assert not is_append_only(Path("projects/my-proj/updates/something.yaml"))

    def test_regular_file(self):
        assert not is_append_only(Path("projects/my-proj/people.md"))

    def test_notes(self):
        assert not is_append_only(Path("projects/my-proj/notes/design.md"))


class TestIsManifest:
    def test_index_yaml(self):
        assert is_manifest(Path("projects/my-proj/_index.yaml"))

    def test_other_yaml(self):
        assert not is_manifest(Path("projects/my-proj/_meta.yaml"))

    def test_md(self):
        assert not is_manifest(Path("projects/my-proj/people.md"))


class TestParseRefs:
    def test_refs(self):
        result = parse_refs("Hello @john-doe and @acme-corp")
        assert "john-doe" in result["refs"]
        assert "acme-corp" in result["refs"]

    def test_tags(self):
        result = parse_refs("Related to #python and #fastmcp")
        assert "python" in result["tags"]
        assert "fastmcp" in result["tags"]

    def test_links(self):
        result = parse_refs("See [[API Design]] and [[Auth Flow]]")
        assert "API Design" in result["links"]
        assert "Auth Flow" in result["links"]

    def test_empty(self):
        result = parse_refs("No refs here")
        assert result == {"refs": [], "tags": [], "links": []}


class TestValidateKnowledgeFrontmatter:
    def test_valid(self):
        content = "---\nsource: null\nprocessed: null\n---\n\n# Topic"
        ok, errors = validate_knowledge_frontmatter(content)
        assert ok
        assert errors == []

    def test_missing_frontmatter(self):
        ok, errors = validate_knowledge_frontmatter("# No frontmatter")
        assert not ok
        assert len(errors) > 0

    def test_unclosed_frontmatter(self):
        ok, errors = validate_knowledge_frontmatter("---\nsource: null\n")
        assert not ok

    def test_invalid_yaml(self):
        ok, errors = validate_knowledge_frontmatter("---\n: bad: yaml: here:\n---\n")
        assert not ok


# ---------------------------------------------------------------------------
# Integration tests — MemoryFS
# ---------------------------------------------------------------------------


@pytest.fixture
def fs(tmp_path):
    """Create an initialised MemoryFS in a temp directory."""
    memory_fs = MemoryFS(tmp_path)
    memory_fs.initialise()
    return memory_fs


class TestMemoryFSInitialise:
    def test_creates_projects_index(self, fs):
        assert (fs.root / "_projects-index.json").exists()

    def test_creates_refs_index(self, fs):
        assert (fs.root / "_refs-index.json").exists()

    def test_creates_root_manifest(self, fs):
        assert (fs.root / "_index.yaml").exists()

    def test_creates_global_people(self, fs):
        assert (fs.root / "_global" / "people" / "_index.yaml").exists()

    def test_creates_global_companies(self, fs):
        assert (fs.root / "_global" / "companies" / "_index.yaml").exists()

    def test_creates_templates(self, fs):
        assert (fs.root / "_templates" / "project-guide.md").exists()

    def test_creates_projects_dir(self, fs):
        assert (fs.root / "projects").is_dir()

    def test_creates_trash_dir(self, fs):
        assert (fs.root / "_trash").is_dir()


class TestScaffoldProject:
    def test_creates_project_dir(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        assert (fs.root / "projects" / "test-proj").is_dir()

    def test_creates_subfolders(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        for sub in ("knowledge", "correspondence", "updates", "docs", "notes"):
            assert (fs.root / "projects" / "test-proj" / sub).is_dir()

    def test_creates_meta_yaml(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        assert (fs.root / "projects" / "test-proj" / "_meta.yaml").exists()

    def test_creates_core_files(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        for f in ("people.md", "companies.md", "decisions.md", "_guide.md"):
            assert (fs.root / "projects" / "test-proj" / f).exists()

    def test_updates_projects_index(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        pi = fs.load_projects_index()
        assert any(p.slug == "test-proj" for p in pi.projects)

    def test_duplicate_slug_raises(self, fs):
        meta = make_meta()
        fs.scaffold_project("test-proj", meta)
        with pytest.raises(ValueError):
            fs.scaffold_project("test-proj", meta)


class TestWriteFile:
    def test_writes_content(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/design.md", "# Design\n\nContent")
        assert (fs.root / "projects" / "test-proj" / "notes" / "design.md").exists()

    def test_blocks_index_yaml(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="_index.yaml"):
            fs.write_file("projects/test-proj/_index.yaml", "bad")

    def test_blocks_decisions_write(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="append-only"):
            fs.write_file("projects/test-proj/decisions.md", "overwrite")

    def test_blocks_updates_write(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="append-only"):
            fs.write_file("projects/test-proj/updates/2025-01-15.md", "overwrite")

    def test_warns_unresolved_ref(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        warnings = fs.write_file("projects/test-proj/notes/note.md", "See @unknown-person")
        assert any("unknown-person" in w for w in warnings)

    def test_updates_manifest(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note", description="My note")
        manifest = fs.load_manifest(fs.root / "projects" / "test-proj" / "notes")
        assert any(e.name == "note.md" and e.description == "My note" for e in manifest.files)

    def test_updates_refs_index(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "See #python")
        refs_index = fs.load_refs_index()
        rel = "projects/test-proj/notes/note.md"
        assert rel in refs_index.entries
        assert "python" in refs_index.entries[rel].tags


class TestAppendFile:
    def test_appends_to_decisions(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.append_file("projects/test-proj/decisions.md", "\n## Decision 1")
        content = (fs.root / "projects" / "test-proj" / "decisions.md").read_text()
        assert "Decision 1" in content

    def test_blocks_non_append_only(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError):
            fs.append_file("projects/test-proj/people.md", "extra")

    def test_blocks_index_yaml(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError):
            fs.append_file("projects/test-proj/_index.yaml", "bad")

    def test_marks_manifest_stale(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.append_file("projects/test-proj/decisions.md", "\n## Decision")
        manifest = fs.load_manifest(fs.root / "projects" / "test-proj")
        assert manifest.stale


class TestSoftDelete:
    def test_moves_to_trash(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note")
        trash_path = fs.soft_delete("projects/test-proj/notes/note.md")
        assert not (fs.root / "projects" / "test-proj" / "notes" / "note.md").exists()
        assert (fs.root / "_trash").exists()
        assert "_trash" in trash_path

    def test_removes_manifest_entry(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note")
        fs.soft_delete("projects/test-proj/notes/note.md")
        manifest = fs.load_manifest(fs.root / "projects" / "test-proj" / "notes")
        assert not any(e.name == "note.md" for e in manifest.files)

    def test_missing_file_raises(self, fs):
        with pytest.raises(FileNotFoundError):
            fs.soft_delete("projects/missing/notes/note.md")


class TestSearchFiles:
    def test_finds_keyword(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note\n\nWe chose Python.")
        results = fs.search_files("Python")
        assert any(r["line_no"] > 0 and "Python" in r["line"] for r in results)

    def test_case_insensitive(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note\n\nWe chose PYTHON.")
        results = fs.search_files("python")
        assert len(results) > 0

    def test_folder_filter(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/note.md", "# Note\n\nPython here.")
        results = fs.search_files("Python", folder="projects/test-proj/notes")
        assert len(results) > 0

    def test_no_results(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        results = fs.search_files("xyzzy-no-such-keyword")
        assert results == []


class TestGlobalEntities:
    def test_create_person(self, fs):
        path = fs.create_person("john-doe", "John Doe", description="Lead engineer")
        assert path.exists()
        content = path.read_text()
        assert "John Doe" in content

    def test_create_person_updates_manifest(self, fs):
        fs.create_person("john-doe", "John Doe")
        manifest = fs.load_manifest(fs.root / "_global" / "people")
        assert any(e.name == "john-doe.md" for e in manifest.files)

    def test_create_person_duplicate_raises(self, fs):
        fs.create_person("john-doe", "John Doe")
        with pytest.raises(ValueError):
            fs.create_person("john-doe", "John Doe 2")

    def test_create_company(self, fs):
        path = fs.create_company("acme-corp", "ACME Corp")
        assert path.exists()
        content = path.read_text()
        assert "ACME Corp" in content

    def test_resolve_ref_person(self, fs):
        fs.create_person("john-doe", "John Doe")
        path, content = fs.resolve_ref("john-doe")
        assert "John Doe" in content

    def test_resolve_ref_company(self, fs):
        fs.create_company("acme-corp", "ACME Corp")
        path, content = fs.resolve_ref("acme-corp")
        assert "ACME Corp" in content

    def test_resolve_ref_not_found(self, fs):
        with pytest.raises(FileNotFoundError):
            fs.resolve_ref("unknown-slug")


class TestStaleManifests:
    def test_stale_after_append(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.append_file("projects/test-proj/decisions.md", "\n## Decision")
        stale = fs.list_stale_manifests()
        assert "projects/test-proj" in stale

    def test_not_stale_initially(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        stale = fs.list_stale_manifests()
        assert "projects/test-proj" not in stale


# ---------------------------------------------------------------------------
# Integration tests — MCP Server tools
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_server(tmp_path):
    return create_server(tmp_path)


class TestMCPTools:
    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_create_project(self, mcp_server):
        r = parse_result(self._call(mcp_server, "create_project", slug="my-proj", name="My Project"))
        assert "error" not in r
        assert r["result"]["slug"] == "my-proj"

    def test_create_project_duplicate(self, mcp_server):
        self._call(mcp_server, "create_project", slug="dup-proj", name="Dup")
        r = parse_result(self._call(mcp_server, "create_project", slug="dup-proj", name="Dup 2"))
        assert "error" in r

    def test_create_project_invalid_slug(self, mcp_server):
        r = parse_result(self._call(mcp_server, "create_project", slug="My Project", name="My Project"))
        assert "error" in r

    def test_create_project_invalid_status(self, mcp_server):
        r = parse_result(self._call(mcp_server, "create_project", slug="my-proj", name="My", status="unknown"))
        assert "error" in r

    def test_list_projects(self, mcp_server):
        self._call(mcp_server, "create_project", slug="proj-a", name="Project A", status="active")
        self._call(mcp_server, "create_project", slug="proj-b", name="Project B", status="paused")
        r = parse_result(self._call(mcp_server, "list_projects"))
        slugs = [p["slug"] for p in r["result"]]
        assert "proj-a" in slugs and "proj-b" in slugs

    def test_list_projects_filter_status(self, mcp_server):
        self._call(mcp_server, "create_project", slug="proj-active", name="Active", status="active")
        self._call(mcp_server, "create_project", slug="proj-paused", name="Paused", status="paused")
        r = parse_result(self._call(mcp_server, "list_projects", status="active"))
        slugs = [p["slug"] for p in r["result"]]
        assert "proj-active" in slugs
        assert "proj-paused" not in slugs

    def test_get_project_context(self, mcp_server):
        self._call(mcp_server, "create_project", slug="ctx-proj", name="Context Project")
        r = parse_result(self._call(mcp_server, "get_project_context", slug="ctx-proj"))
        assert "error" not in r
        assert r["result"]["meta"] is not None
        assert "ctx-proj" in r["result"]["manifest"] or "Folder Manifest" in r["result"]["manifest"]

    def test_get_project_context_not_found(self, mcp_server):
        r = parse_result(self._call(mcp_server, "get_project_context", slug="no-such-proj"))
        assert "error" in r

    def test_write_and_read_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="rw-proj", name="RW")
        self._call(mcp_server, "write_file",
                   path="projects/rw-proj/notes/note.md",
                   content="# Test Note\n\nContent here.")
        r = parse_result(self._call(mcp_server, "read_file", path="projects/rw-proj/notes/note.md"))
        assert "Content here" in r["result"]

    def test_read_file_blocks_index_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="block-proj", name="Block")
        r = parse_result(self._call(mcp_server, "read_file", path="projects/block-proj/_index.yaml"))
        assert "error" in r

    def test_write_file_blocks_index_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="wblock-proj", name="WBlock")
        r = parse_result(self._call(mcp_server, "write_file",
                                    path="projects/wblock-proj/_index.yaml",
                                    content="bad"))
        assert "error" in r

    def test_append_to_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="app-proj", name="Append")
        r = parse_result(self._call(mcp_server, "append_to_file",
                                    path="projects/app-proj/decisions.md",
                                    content="\n## Decision 1\n\nWe chose REST."))
        assert "error" not in r

    def test_get_folder_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="mani-proj", name="Manifest")
        self._call(mcp_server, "write_file",
                   path="projects/mani-proj/notes/note.md",
                   content="# Note",
                   description="A test note")
        r = parse_result(self._call(mcp_server, "get_folder_manifest",
                                    folder_path="projects/mani-proj/notes"))
        assert "error" not in r
        assert "note.md" in r["result"]

    def test_update_file_description(self, mcp_server):
        self._call(mcp_server, "create_project", slug="upd-proj", name="Update")
        self._call(mcp_server, "write_file",
                   path="projects/upd-proj/notes/note.md",
                   content="# Note")
        r = parse_result(self._call(mcp_server, "update_file_description",
                                    folder_path="projects/upd-proj/notes",
                                    filename="note.md",
                                    description="Updated description",
                                    read_when="When reviewing notes"))
        assert "error" not in r

    def test_search_files(self, mcp_server):
        self._call(mcp_server, "create_project", slug="srch-proj", name="Search")
        self._call(mcp_server, "write_file",
                   path="projects/srch-proj/notes/note.md",
                   content="# Design\n\nWe chose Python for this.")
        r = parse_result(self._call(mcp_server, "search_files", keyword="Python"))
        assert any("Python" in result["line"] for result in r["result"])

    def test_delete_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="del-proj", name="Delete")
        self._call(mcp_server, "write_file",
                   path="projects/del-proj/notes/note.md",
                   content="# Note to delete")
        r = parse_result(self._call(mcp_server, "delete_file",
                                    path="projects/del-proj/notes/note.md"))
        assert "error" not in r
        assert "_trash" in r["result"]

    def test_list_stale_manifests(self, mcp_server):
        self._call(mcp_server, "create_project", slug="stale-proj", name="Stale")
        self._call(mcp_server, "append_to_file",
                   path="projects/stale-proj/decisions.md",
                   content="\n## Decision")
        r = parse_result(self._call(mcp_server, "list_stale_manifests"))
        assert "projects/stale-proj" in r["result"]

    def test_create_person(self, mcp_server):
        r = parse_result(self._call(mcp_server, "create_person",
                                    slug="jane-smith",
                                    name="Jane Smith",
                                    title="CTO",
                                    email="jane@test.com"))
        assert "error" not in r
        assert "Jane Smith" in r["result"]["message"]

    def test_create_company(self, mcp_server):
        r = parse_result(self._call(mcp_server, "create_company",
                                    slug="test-corp",
                                    name="Test Corp",
                                    industry="Technology"))
        assert "error" not in r

    def test_get_person(self, mcp_server):
        self._call(mcp_server, "create_person", slug="get-person", name="Get Person")
        r = parse_result(self._call(mcp_server, "get_person", slug="get-person"))
        assert "error" not in r
        assert "Get Person" in r["result"]

    def test_get_company(self, mcp_server):
        self._call(mcp_server, "create_company", slug="get-corp", name="Get Corp")
        r = parse_result(self._call(mcp_server, "get_company", slug="get-corp"))
        assert "error" not in r
        assert "Get Corp" in r["result"]

    def test_resolve_ref(self, mcp_server):
        self._call(mcp_server, "create_person", slug="ref-person", name="Ref Person")
        r = parse_result(self._call(mcp_server, "resolve_ref", slug="ref-person"))
        assert "error" not in r
        assert "Ref Person" in r["result"]["content"]

    def test_resolve_ref_not_found(self, mcp_server):
        r = parse_result(self._call(mcp_server, "resolve_ref", slug="no-one"))
        assert "error" in r

    def test_create_knowledge_entry(self, mcp_server):
        self._call(mcp_server, "create_project", slug="know-proj", name="Knowledge")
        r = parse_result(self._call(mcp_server, "create_knowledge_entry",
                                    project_slug="know-proj",
                                    topic="auth-design",
                                    content="OAuth2 chosen.",
                                    frontmatter={"source": "meeting", "processed": "2025-01-15"},
                                    description="Auth design decision",
                                    read_when="Before coding auth"))
        assert "error" not in r
        assert "auth-design" in r["result"]

    def test_update_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="rebuild-proj", name="Rebuild")
        r = parse_result(self._call(mcp_server, "update_manifest",
                                    folder_path="projects/rebuild-proj"))
        assert "error" not in r
