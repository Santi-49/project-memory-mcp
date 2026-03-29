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
    is_updates_folder,
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

    def test_blocks_project_people_write(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="auto-managed"):
            fs.write_file("projects/test-proj/people.md", "manual edit")

    def test_warns_unresolved_ref(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        warnings = fs.write_file(
            "projects/test-proj/notes/note.md", "See @unknown-person"
        )
        assert any("unknown-person" in w for w in warnings)

    def test_updates_manifest(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md", "# Note", description="My note"
        )
        manifest = fs.load_manifest(fs.root / "projects" / "test-proj" / "notes")
        assert any(
            e.name == "note.md" and e.description == "My note" for e in manifest.files
        )

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

    def test_updates_append_new_file_is_indexed(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.append_file(
            "projects/test-proj/updates/005-final-test.md", "\n## Final update"
        )
        manifest = fs.load_manifest(fs.root / "projects" / "test-proj" / "updates")
        assert any(e.name == "005-final-test.md" for e in manifest.files)


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

    def test_blocks_project_people_delete(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="auto-managed"):
            fs.soft_delete("projects/test-proj/people.md")


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

    def test_link_person_to_project_updates_both_files(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.create_person("john-doe", "John Doe", extra_fields={"Company": "ACME"})

        person_path, project_people_path = fs.link_person_to_project(
            "john-doe", "test-proj"
        )

        person_content = person_path.read_text(encoding="utf-8")
        project_people = project_people_path.read_text(encoding="utf-8")

        assert "[[test-proj]]" in person_content
        assert "## ACME" in project_people
        assert "@john-doe" in project_people

    def test_unlink_person_from_project_removes_person(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.create_person("john-doe", "John Doe", extra_fields={"Company": "ACME"})
        fs.link_person_to_project("john-doe", "test-proj")

        fs.unlink_person_from_project("john-doe", "test-proj")

        person_content = (fs.root / "_global" / "people" / "john-doe.md").read_text(
            encoding="utf-8"
        )
        project_people = (fs.root / "projects" / "test-proj" / "people.md").read_text(
            encoding="utf-8"
        )

        assert "[[test-proj]]" not in person_content
        assert "@john-doe" not in project_people

    def test_edit_person_notes_append(self, fs):
        fs.create_person("john-doe", "John Doe")
        path, warnings = fs.edit_person_notes(
            "john-doe", "First manual note", mode="append"
        )
        content = path.read_text(encoding="utf-8")
        assert "## Notes" in content
        assert "First manual note" in content
        assert warnings == []

    def test_edit_person_notes_replace(self, fs):
        fs.create_person("john-doe", "John Doe")
        fs.edit_person_notes("john-doe", "Old note", mode="append")
        path, _ = fs.edit_person_notes("john-doe", "Fresh note", mode="replace")
        content = path.read_text(encoding="utf-8")
        assert "Fresh note" in content
        assert "Old note" not in content


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
        r = parse_result(
            self._call(mcp_server, "create_project", slug="my-proj", name="My Project")
        )
        assert "error" not in r
        assert r["result"]["slug"] == "my-proj"

    def test_create_project_duplicate(self, mcp_server):
        self._call(mcp_server, "create_project", slug="dup-proj", name="Dup")
        r = parse_result(
            self._call(mcp_server, "create_project", slug="dup-proj", name="Dup 2")
        )
        assert "error" in r

    def test_create_project_invalid_slug(self, mcp_server):
        r = parse_result(
            self._call(
                mcp_server, "create_project", slug="My Project", name="My Project"
            )
        )
        assert "error" in r

    def test_create_project_invalid_status(self, mcp_server):
        r = parse_result(
            self._call(
                mcp_server,
                "create_project",
                slug="my-proj",
                name="My",
                status="unknown",
            )
        )
        assert "error" in r

    def test_list_projects(self, mcp_server):
        self._call(
            mcp_server,
            "create_project",
            slug="proj-a",
            name="Project A",
            status="active",
        )
        self._call(
            mcp_server,
            "create_project",
            slug="proj-b",
            name="Project B",
            status="paused",
        )
        r = parse_result(self._call(mcp_server, "list_projects"))
        slugs = [p["slug"] for p in r["result"]]
        assert "proj-a" in slugs and "proj-b" in slugs

    def test_list_projects_filter_status(self, mcp_server):
        self._call(
            mcp_server,
            "create_project",
            slug="proj-active",
            name="Active",
            status="active",
        )
        self._call(
            mcp_server,
            "create_project",
            slug="proj-paused",
            name="Paused",
            status="paused",
        )
        r = parse_result(self._call(mcp_server, "list_projects", status="active"))
        slugs = [p["slug"] for p in r["result"]]
        assert "proj-active" in slugs
        assert "proj-paused" not in slugs

    def test_get_project_context(self, mcp_server):
        self._call(
            mcp_server, "create_project", slug="ctx-proj", name="Context Project"
        )
        r = parse_result(self._call(mcp_server, "get_project_context", slug="ctx-proj"))
        assert "error" not in r
        assert r["result"]["meta"] is not None
        assert (
            "ctx-proj" in r["result"]["manifest"]
            or "Folder Manifest" in r["result"]["manifest"]
        )

    def test_get_project_context_not_found(self, mcp_server):
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="no-such-proj")
        )
        assert "error" in r

    def test_write_and_read_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="rw-proj", name="RW")
        self._call(
            mcp_server,
            "write_file",
            path="projects/rw-proj/notes/note.md",
            content="# Test Note\n\nContent here.",
        )
        r = parse_result(
            self._call(mcp_server, "read_file", path="projects/rw-proj/notes/note.md")
        )
        assert "Content here" in r["result"]

    def test_read_file_blocks_index_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="block-proj", name="Block")
        r = parse_result(
            self._call(mcp_server, "read_file", path="projects/block-proj/_index.yaml")
        )
        assert "error" in r

    def test_write_file_blocks_index_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="wblock-proj", name="WBlock")
        r = parse_result(
            self._call(
                mcp_server,
                "write_file",
                path="projects/wblock-proj/_index.yaml",
                content="bad",
            )
        )
        assert "error" in r

    def test_write_file_blocks_project_people(self, mcp_server):
        self._call(
            mcp_server, "create_project", slug="people-lock-proj", name="People Lock"
        )
        r = parse_result(
            self._call(
                mcp_server,
                "write_file",
                path="projects/people-lock-proj/people.md",
                content="manual edit",
            )
        )
        assert "error" in r

    def test_append_to_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="app-proj", name="Append")
        r = parse_result(
            self._call(
                mcp_server,
                "append_to_file",
                path="projects/app-proj/decisions.md",
                content="\n## Decision 1\n\nWe chose REST.",
            )
        )
        assert "error" not in r

    def test_get_folder_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="mani-proj", name="Manifest")
        self._call(
            mcp_server,
            "write_file",
            path="projects/mani-proj/notes/note.md",
            content="# Note",
            description="A test note",
        )
        r = parse_result(
            self._call(
                mcp_server,
                "get_folder_manifest",
                folder_path="projects/mani-proj/notes",
            )
        )
        assert "error" not in r
        assert "note.md" in r["result"]

    def test_update_file_description(self, mcp_server):
        self._call(mcp_server, "create_project", slug="upd-proj", name="Update")
        self._call(
            mcp_server,
            "write_file",
            path="projects/upd-proj/notes/note.md",
            content="# Note",
        )
        r = parse_result(
            self._call(
                mcp_server,
                "update_file_description",
                folder_path="projects/upd-proj/notes",
                filename="note.md",
                description="Updated description",
                read_when="When reviewing notes",
            )
        )
        assert "error" not in r

    def test_search_files(self, mcp_server):
        self._call(mcp_server, "create_project", slug="srch-proj", name="Search")
        self._call(
            mcp_server,
            "write_file",
            path="projects/srch-proj/notes/note.md",
            content="# Design\n\nWe chose Python for this.",
        )
        r = parse_result(self._call(mcp_server, "search_files", keyword="Python"))
        assert any("Python" in result["line"] for result in r["result"])

    def test_delete_file(self, mcp_server):
        self._call(mcp_server, "create_project", slug="del-proj", name="Delete")
        self._call(
            mcp_server,
            "write_file",
            path="projects/del-proj/notes/note.md",
            content="# Note to delete",
        )
        r = parse_result(
            self._call(
                mcp_server, "delete_file", path="projects/del-proj/notes/note.md"
            )
        )
        assert "error" not in r
        assert "_trash" in r["result"]

    def test_list_stale_manifests(self, mcp_server):
        self._call(mcp_server, "create_project", slug="stale-proj", name="Stale")
        self._call(
            mcp_server,
            "append_to_file",
            path="projects/stale-proj/decisions.md",
            content="\n## Decision",
        )
        r = parse_result(self._call(mcp_server, "list_stale_manifests"))
        assert "projects/stale-proj" in r["result"]

    def test_create_person(self, mcp_server):
        r = parse_result(
            self._call(
                mcp_server,
                "create_person",
                slug="jane-smith",
                name="Jane Smith",
                title="CTO",
                email="jane@test.com",
            )
        )
        assert "error" not in r
        assert "Jane Smith" in r["result"]["message"]

    def test_create_person_with_project_slug_links_person(self, mcp_server):
        self._call(mcp_server, "create_project", slug="cp-link-proj", name="CP Link")
        r = parse_result(
            self._call(
                mcp_server,
                "create_person",
                slug="cp-link-person",
                name="CP Link Person",
                company="Other",
                project_slug="cp-link-proj",
            )
        )
        assert "error" not in r
        assert r["result"]["linked_project"] == "cp-link-proj"

        people_file = parse_result(
            self._call(mcp_server, "read_file", path="projects/cp-link-proj/people.md")
        )
        assert "@cp-link-person" in people_file["result"]

    def test_create_company(self, mcp_server):
        r = parse_result(
            self._call(
                mcp_server,
                "create_company",
                slug="test-corp",
                name="Test Corp",
                industry="Technology",
            )
        )
        assert "error" not in r

    def test_get_person(self, mcp_server):
        self._call(mcp_server, "create_person", slug="get-person", name="Get Person")
        r = parse_result(self._call(mcp_server, "get_person", slug="get-person"))
        assert "error" not in r
        assert "Get Person" in r["result"]

    def test_link_and_unlink_person_project(self, mcp_server):
        self._call(mcp_server, "create_project", slug="link-proj", name="Link Project")
        self._call(
            mcp_server,
            "create_person",
            slug="link-person",
            name="Link Person",
            company="Other",
        )

        linked = parse_result(
            self._call(
                mcp_server,
                "link_person_to_project",
                person_slug="link-person",
                project_slug="link-proj",
            )
        )
        assert "error" not in linked

        people_file = parse_result(
            self._call(mcp_server, "read_file", path="projects/link-proj/people.md")
        )
        assert "@link-person" in people_file["result"]

        unlinked = parse_result(
            self._call(
                mcp_server,
                "unlink_person_from_project",
                person_slug="link-person",
                project_slug="link-proj",
            )
        )
        assert "error" not in unlinked

        people_after = parse_result(
            self._call(mcp_server, "read_file", path="projects/link-proj/people.md")
        )
        assert "@link-person" not in people_after["result"]

    def test_edit_person_notes_tool(self, mcp_server):
        self._call(
            mcp_server, "create_person", slug="notes-person", name="Notes Person"
        )

        append_result = parse_result(
            self._call(
                mcp_server,
                "edit_person_notes",
                slug="notes-person",
                notes="Manual note line 1",
                mode="append",
            )
        )
        assert "error" not in append_result

        person_result = parse_result(
            self._call(mcp_server, "get_person", slug="notes-person")
        )
        assert "Manual note line 1" in person_result["result"]

        replace_result = parse_result(
            self._call(
                mcp_server,
                "edit_person_notes",
                slug="notes-person",
                notes="Replaced note",
                mode="replace",
            )
        )
        assert "error" not in replace_result

        person_result2 = parse_result(
            self._call(mcp_server, "get_person", slug="notes-person")
        )
        assert "Replaced note" in person_result2["result"]
        assert "Manual note line 1" not in person_result2["result"]

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
        r = parse_result(
            self._call(
                mcp_server,
                "create_knowledge_entry",
                project_slug="know-proj",
                topic="auth-design",
                content="OAuth2 chosen.",
                frontmatter={"source": "meeting", "processed": "2025-01-15"},
                description="Auth design decision",
                read_when="Before coding auth",
            )
        )
        assert "error" not in r
        assert "auth-design" in r["result"]

    def test_update_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="rebuild-proj", name="Rebuild")
        r = parse_result(
            self._call(
                mcp_server, "update_manifest", folder_path="projects/rebuild-proj"
            )
        )
        assert "error" not in r

    def test_updates_append_file_visible_in_folder_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="updates-proj", name="Updates")
        self._call(
            mcp_server,
            "append_to_file",
            path="projects/updates-proj/updates/001-setup.md",
            content="\n## Setup\n",
        )
        self._call(
            mcp_server,
            "append_to_file",
            path="projects/updates-proj/updates/003-final-test.md",
            content="\n## Final test\n",
        )

        manifest_result = parse_result(
            self._call(
                mcp_server,
                "get_folder_manifest",
                folder_path="projects/updates-proj/updates",
            )
        )
        assert "error" not in manifest_result
        assert "003-final-test.md" in manifest_result["result"]

        rebuild_result = parse_result(
            self._call(
                mcp_server,
                "update_manifest",
                folder_path="projects/updates-proj/updates",
            )
        )
        assert "error" not in rebuild_result
        assert "2 entries" in rebuild_result["result"]


# ---------------------------------------------------------------------------
# New tests — issue requirements
# ---------------------------------------------------------------------------


class TestIsUpdatesFolder:
    def test_updates_folder(self):
        assert is_updates_folder(Path("projects/my-proj/updates"))

    def test_not_updates_folder(self):
        assert not is_updates_folder(Path("projects/my-proj/notes"))

    def test_root_level_updates(self):
        # only name matters, not depth
        assert is_updates_folder(Path("updates"))


class TestGuideTemplate:
    """_guide.md must use | Folder | Contains | Read when | columns and include _status.md."""

    def test_column_headers(self):
        from templates import PROJECT_GUIDE_TEMPLATE

        assert "| Folder / File | Contains | Read when |" in PROJECT_GUIDE_TEMPLATE

    def test_includes_status_md(self):
        from templates import PROJECT_GUIDE_TEMPLATE

        assert "_status.md" in PROJECT_GUIDE_TEMPLATE

    def test_scaffold_guide_uses_template(self, fs):
        fs.scaffold_project("g-proj", make_meta(slug="g-proj"))
        guide = (fs.root / "projects" / "g-proj" / "_guide.md").read_text()
        assert "| Folder / File | Contains | Read when |" in guide
        assert "_status.md" in guide

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestStatusMd:
    """_status.md must be created at scaffold and loaded first in get_project_context."""

    def test_scaffold_creates_status_md(self, fs):
        fs.scaffold_project("s-proj", make_meta(slug="s-proj"))
        assert (fs.root / "projects" / "s-proj" / "_status.md").exists()

    def test_status_md_content(self, fs):
        fs.scaffold_project("s-proj", make_meta(slug="s-proj", name="Status Test"))
        content = (fs.root / "projects" / "s-proj" / "_status.md").read_text()
        assert "Status Test" in content
        assert "Current state:" in content
        assert "Next action:" in content

    def test_status_md_in_manifest(self, fs):
        fs.scaffold_project("s-proj", make_meta(slug="s-proj"))
        manifest = fs.load_manifest(fs.root / "projects" / "s-proj")
        entry = next((e for e in manifest.files if e.name == "_status.md"), None)
        assert entry is not None
        assert "First" in entry.read_when or "first" in entry.read_when

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestGetProjectContextDeep:
    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_shallow_includes_status(self, mcp_server):
        self._call(mcp_server, "create_project", slug="deep-proj", name="Deep Test")
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="deep-proj")
        )
        assert "error" not in r
        assert "status" in r["result"]
        assert r["result"]["status"] is not None

    def test_shallow_has_no_deep_keys(self, mcp_server):
        self._call(mcp_server, "create_project", slug="shallow-proj", name="Shallow")
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="shallow-proj")
        )
        assert "error" not in r
        assert "knowledge_manifest" not in r["result"]
        assert "people" not in r["result"]

    def test_deep_includes_knowledge_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="deep2-proj", name="Deep2")
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="deep2-proj", deep=True)
        )
        assert "error" not in r
        assert "knowledge_manifest" in r["result"]
        assert "people" in r["result"]

    def test_deep_knowledge_manifest_is_string(self, mcp_server):
        self._call(mcp_server, "create_project", slug="deep3-proj", name="Deep3")
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="deep3-proj", deep=True)
        )
        assert isinstance(r["result"]["knowledge_manifest"], str)

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestSearchFilesProjectSlug:
    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_project_slug_scopes_search(self, mcp_server):
        self._call(mcp_server, "create_project", slug="proj-a", name="Proj A")
        self._call(mcp_server, "create_project", slug="proj-b", name="Proj B")
        self._call(
            mcp_server,
            "write_file",
            path="projects/proj-a/notes/note.md",
            content="# Note\n\nUniqueTermAlpha here.",
        )
        self._call(
            mcp_server,
            "write_file",
            path="projects/proj-b/notes/note.md",
            content="# Note\n\nDifferent content.",
        )
        # Search within proj-a only
        r = parse_result(
            self._call(
                mcp_server,
                "search_files",
                keyword="UniqueTermAlpha",
                project_slug="proj-a",
            )
        )
        assert len(r["result"]) > 0
        assert all("proj-a" in hit["path"] for hit in r["result"])

    def test_project_slug_excludes_other_projects(self, mcp_server):
        self._call(mcp_server, "create_project", slug="src-a", name="Src A")
        self._call(mcp_server, "create_project", slug="src-b", name="Src B")
        self._call(
            mcp_server,
            "write_file",
            path="projects/src-a/notes/note.md",
            content="# SharedKeyword",
        )
        self._call(
            mcp_server,
            "write_file",
            path="projects/src-b/notes/note.md",
            content="# SharedKeyword",
        )
        r = parse_result(
            self._call(
                mcp_server,
                "search_files",
                keyword="SharedKeyword",
                project_slug="src-a",
            )
        )
        assert all("src-a" in hit["path"] for hit in r["result"])
        assert not any("src-b" in hit["path"] for hit in r["result"])

    def test_project_slug_not_found_returns_error(self, mcp_server):
        r = parse_result(
            self._call(
                mcp_server,
                "search_files",
                keyword="anything",
                project_slug="no-such-proj",
            )
        )
        assert "error" in r

    def test_no_filter_searches_everywhere(self, mcp_server):
        self._call(mcp_server, "create_project", slug="glob-proj", name="Global")
        self._call(
            mcp_server,
            "write_file",
            path="projects/glob-proj/notes/note.md",
            content="# GlobalSearchTerm found here.",
        )
        r = parse_result(
            self._call(mcp_server, "search_files", keyword="GlobalSearchTerm")
        )
        assert len(r["result"]) > 0

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestListGlobalPeopleCompanies:
    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_list_global_people_empty(self, mcp_server):
        r = parse_result(self._call(mcp_server, "list_global_people"))
        assert "error" not in r
        assert r["result"] == []

    def test_list_global_people_after_create(self, mcp_server):
        self._call(
            mcp_server, "create_person", slug="alice-wonder", name="Alice Wonder"
        )
        self._call(mcp_server, "create_person", slug="bob-builder", name="Bob Builder")
        r = parse_result(self._call(mcp_server, "list_global_people"))
        assert "error" not in r
        names = [e["name"] for e in r["result"]]
        assert "alice-wonder.md" in names
        assert "bob-builder.md" in names

    def test_list_global_companies_empty(self, mcp_server):
        r = parse_result(self._call(mcp_server, "list_global_companies"))
        assert "error" not in r
        assert r["result"] == []

    def test_list_global_companies_after_create(self, mcp_server):
        self._call(mcp_server, "create_company", slug="widget-corp", name="Widget Corp")
        r = parse_result(self._call(mcp_server, "list_global_companies"))
        assert "error" not in r
        names = [e["name"] for e in r["result"]]
        assert "widget-corp.md" in names

    def test_list_people_entries_have_description(self, mcp_server):
        self._call(
            mcp_server,
            "create_person",
            slug="desc-person",
            name="Desc Person",
            description="A described person",
        )
        r = parse_result(self._call(mcp_server, "list_global_people"))
        entry = next(e for e in r["result"] if e["name"] == "desc-person.md")
        assert entry["description"] == "A described person"

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestRebuildRefsIndex:
    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_rebuild_refs_index_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="refs-proj", name="Refs")
        self._call(
            mcp_server,
            "write_file",
            path="projects/refs-proj/notes/note.md",
            content="# Note\n\n@john-doe and #python mentioned.",
        )
        r = parse_result(self._call(mcp_server, "rebuild_refs_index"))
        assert "error" not in r
        assert "indexed" in r["result"]

    def test_rebuild_fixes_drifted_index(self, mcp_server, tmp_path):
        """Rebuild should re-scan files even if the index was corrupted."""
        self._call(mcp_server, "create_project", slug="drift-proj", name="Drift")
        self._call(
            mcp_server,
            "write_file",
            path="projects/drift-proj/notes/note.md",
            content="# Note\n\n#drifted-tag mentioned.",
        )
        # Corrupt the index
        idx_path = tmp_path / "_refs-index.json"
        idx_path.write_text('{"entries": {}}', encoding="utf-8")
        # Rebuild
        r = parse_result(self._call(mcp_server, "rebuild_refs_index"))
        assert "error" not in r
        # Verify the tag is now back in the index
        r2 = parse_result(self._call(mcp_server, "get_refs_for", ref="drifted-tag"))
        assert len(r2["result"]) > 0

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestUpdatesManifestConvention:
    def test_updates_manifest_has_description(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        manifest = fs.load_manifest(fs.root / "projects" / "upd-proj" / "updates")
        assert manifest.description is not None
        assert (
            "log" in manifest.description.lower()
            or "chronological" in manifest.description.lower()
        )

    def test_updates_manifest_has_last_entry_date_null(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        manifest = fs.load_manifest(fs.root / "projects" / "upd-proj" / "updates")
        assert manifest.last_entry_date is None

    def test_append_to_updates_sets_last_entry_date(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        fs.append_file("projects/upd-proj/updates/2025-01-15.md", "\nUpdate content.")
        manifest = fs.load_manifest(fs.root / "projects" / "upd-proj" / "updates")
        assert manifest.last_entry_date is not None

    def test_append_to_updates_does_not_mark_stale(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        fs.append_file("projects/upd-proj/updates/2025-01-15.md", "\nUpdate content.")
        manifest = fs.load_manifest(fs.root / "projects" / "upd-proj" / "updates")
        assert manifest.stale is False

    def test_append_to_decisions_still_marks_stale(self, fs):
        """Stale behaviour for non-updates append-only files must be unchanged."""
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        fs.append_file("projects/upd-proj/decisions.md", "\n## Decision")
        manifest = fs.load_manifest(fs.root / "projects" / "upd-proj")
        assert manifest.stale is True

    def test_rebuild_manifest_updates_folder_keeps_description(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        updates_dir = fs.root / "projects" / "upd-proj" / "updates"
        manifest = fs.rebuild_manifest(updates_dir)
        assert manifest.description is not None
        assert manifest.stale is False

    def test_render_manifest_shows_description_and_last_entry_date(self, fs):
        fs.scaffold_project("upd-proj", make_meta(slug="upd-proj"))
        fs.append_file("projects/upd-proj/updates/2025-01-15.md", "\nUpdate content.")
        text = fs.render_manifest(fs.root / "projects" / "upd-proj" / "updates")
        assert "Description:" in text
        assert "Last entry date:" in text

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestRebuildRefsIndexFS:
    def test_returns_file_count(self, fs):
        fs.scaffold_project("r-proj", make_meta(slug="r-proj"))
        fs.write_file("projects/r-proj/notes/note.md", "# Note\n\n#tag1")
        count = fs.rebuild_refs_index()
        assert count >= 1

    def test_populates_tags(self, fs):
        fs.scaffold_project("r-proj", make_meta(slug="r-proj"))
        fs.write_file("projects/r-proj/notes/note.md", "# Note\n\n#rebuild-tag")
        # Wipe index manually
        (fs.root / "_refs-index.json").write_text('{"entries": {}}', encoding="utf-8")
        fs.rebuild_refs_index()
        refs_index = fs.load_refs_index()
        all_tags = [tag for e in refs_index.entries.values() for tag in e.tags]
        assert "rebuild-tag" in all_tags

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestListGlobalPeopleCompaniesFS:
    def test_list_people_empty(self, fs):
        result = fs.list_global_people()
        assert result == []

    def test_list_people_after_create(self, fs):
        fs.create_person("p1", "Person One")
        fs.create_person("p2", "Person Two")
        result = fs.list_global_people()
        names = [e["name"] for e in result]
        assert "p1.md" in names
        assert "p2.md" in names

    def test_list_companies_empty(self, fs):
        result = fs.list_global_companies()
        assert result == []

    def test_list_companies_after_create(self, fs):
        fs.create_company("c1", "Company One")
        result = fs.list_global_companies()
        names = [e["name"] for e in result]
        assert "c1.md" in names

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestSearchFilesSkipsTrash:
    """search_files must not return results from _trash/."""

    def test_trash_not_searched_globally(self, fs):
        fs.scaffold_project("trash-proj", make_meta(slug="trash-proj"))
        fs.write_file(
            "projects/trash-proj/notes/note.md", "# Note\n\nUniqueTrashKeyword here."
        )
        # Soft-delete — file moves to _trash/
        fs.soft_delete("projects/trash-proj/notes/note.md")
        # Global search must not find it
        results = fs.search_files("UniqueTrashKeyword")
        assert results == [], "Deleted files in _trash/ should not be searchable"

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs


class TestGuideResource:
    """memory://guide resource must exist and contain all required sections."""

    _REQUIRED_HEADINGS = [
        "## What this server manages",
        "## Root structure",
        "## Project folder layout",
        "## Tool inventory",
        "## Reference syntax",
        "## Key schemas",
        "## Filesystem rules",
    ]

    def test_guide_resource_exists(self, mcp_server):
        resources = asyncio.run(mcp_server.list_resources())
        uris = [str(r.uri) for r in resources]
        assert "memory://guide" in uris

    def test_guide_resource_contains_all_sections(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://guide"))
        text = result.contents[0].content
        for heading in self._REQUIRED_HEADINGS:
            assert heading in text, f"Missing section heading: {heading!r}"

    def test_guide_resource_contains_tool_names(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://guide"))
        text = result.contents[0].content
        assert "list_projects" in text
        assert "create_project" in text
        assert "create_person" in text

    def test_guide_resource_is_string(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://guide"))
        assert isinstance(result.contents[0].content, str)
        assert len(result.contents[0].content) > 100

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)
