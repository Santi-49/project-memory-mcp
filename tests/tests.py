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
        assert result["refs"] == []
        assert result["tags"] == []
        assert result["links"] == []
        assert result["m365_refs"] == []


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

    def test_source_as_string(self):
        content = "---\nsource: 'plain text source'\nprocessed: null\n---\n\n# Topic"
        ok, errors = validate_knowledge_frontmatter(content)
        assert ok
        assert errors == []

    def test_source_as_list_of_strings(self):
        content = "---\nsource:\n  - '[sp:sp-contracts/file.pdf]'\n  - '[tm:teams-general/msg123]'\nprocessed: null\n---\n\n# Topic"
        ok, errors = validate_knowledge_frontmatter(content)
        assert ok
        assert errors == []

    def test_source_as_m365_ref_string(self):
        content = "---\nsource: '[sp:sp-contracts/msa-v2.pdf]'\nprocessed: null\n---\n\n# Topic"
        ok, errors = validate_knowledge_frontmatter(content)
        assert ok
        assert errors == []

    def test_source_as_internal_mem_ref(self):
        content = "---\nsource: '[mem:projects/acme/correspondence/q1-thread.md]'\nprocessed: null\n---\n\n# Topic"
        ok, errors = validate_knowledge_frontmatter(content)
        assert ok
        assert errors == []


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


# ---------------------------------------------------------------------------
# M365 Integration Tests
# ---------------------------------------------------------------------------


class TestSyncState:
    """TestSyncState — get/update/add round-trip, missing file handling,
    duplicate id rejection, kebab-case enforcement.
    """

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_get_sync_state_missing_returns_null(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.get_sync_state("test-proj")
        assert result["result"] is None
        assert result["warnings"] == ["No sync state found"]

    def test_add_sync_source_teams_creates_file(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General channel",
            channel_id="19:abc123",
        )
        assert "error" not in result
        assert result["result"]["id"] == "teams-general"
        sync_path = fs.root / "projects" / "test-proj" / "_sync.yaml"
        assert sync_path.exists()

    def test_add_sync_source_outlook(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.add_sync_source(
            "test-proj", "outlook", id="outlook-internal", label="Internal thread",
            folder_id="AAMkAGI2",
        )
        assert "error" not in result
        assert result["result"]["folder_id"] == "AAMkAGI2"

    def test_add_sync_source_sharepoint(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.add_sync_source(
            "test-proj", "sharepoint", id="sp-contracts", label="Contracts library",
            site_url="https://company.sharepoint.com/sites/acme",
            library="Contracts",
        )
        assert "error" not in result
        assert result["result"]["site_url"] == "https://company.sharepoint.com/sites/acme"
        assert result["result"]["library"] == "Contracts"

    def test_add_sync_source_default_fields(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        src = result["result"]
        assert src["last_processed_at"] is None
        assert src["last_message_id"] is None
        assert src["unprocessed_count"] == 0
        assert src["enabled"] is True

    def test_add_sync_source_duplicate_id_raises(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        with pytest.raises(ValueError, match="already exists"):
            fs.add_sync_source(
                "test-proj", "teams", id="teams-general", label="Duplicate",
                channel_id="19:xyz",
            )

    def test_add_sync_source_kebab_case_enforced(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="kebab-case"):
            fs.add_sync_source(
                "test-proj", "teams", id="INVALID_ID", label="Bad",
                channel_id="19:abc",
            )

    def test_add_sync_source_same_id_different_types_allowed(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="general", label="Teams General",
            channel_id="19:abc",
        )
        # Same id but different type is allowed
        result = fs.add_sync_source(
            "test-proj", "outlook", id="general", label="Outlook General",
            folder_id="AAMkAGI2",
        )
        assert "error" not in result

    def test_get_sync_state_round_trip(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        state = fs.get_sync_state("test-proj")
        assert state["result"] is not None
        teams = state["result"]["sources"]["teams"]
        assert any(s["id"] == "teams-general" for s in teams)

    def test_update_sync_state_merges_fields(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        result = fs.update_sync_state(
            "test-proj", "teams", "teams-general",
            {"last_processed_at": "2025-03-28T06:00:00Z", "unprocessed_count": 5},
        )
        assert "error" not in result
        src = result["result"]
        assert src["last_processed_at"] == "2025-03-28T06:00:00Z"
        assert src["unprocessed_count"] == 5
        # Verify persisted
        state = fs.get_sync_state("test-proj")
        teams = state["result"]["sources"]["teams"]
        t = next(s for s in teams if s["id"] == "teams-general")
        assert t["last_processed_at"] == "2025-03-28T06:00:00Z"

    def test_update_sync_state_unknown_source_raises(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        with pytest.raises(ValueError, match="not found"):
            fs.update_sync_state(
                "test-proj", "teams", "unknown-source",
                {"last_processed_at": "2025-03-28T06:00:00Z"},
            )

    def test_update_sync_state_pipeline(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        result = fs.update_sync_state(
            "test-proj", "pipeline", "",
            {"last_knowledge_synthesis": "2025-03-28", "next_knowledge_synthesis": "2025-04-04"},
        )
        assert "error" not in result
        state = fs.get_sync_state("test-proj")
        pipeline = state["result"]["pipeline"]
        assert pipeline["last_knowledge_synthesis"] == "2025-03-28"
        assert pipeline["next_knowledge_synthesis"] == "2025-04-04"

    def test_update_sync_state_creates_sync_yaml_if_missing(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general", label="General",
            channel_id="19:abc",
        )
        # File already created by add_sync_source; test update creates it if not there
        sync_path = fs.root / "projects" / "test-proj" / "_sync.yaml"
        sync_path.unlink()
        # update_sync_state creates minimal structure first, but since source doesn't
        # exist in the new empty file, it should raise
        with pytest.raises(ValueError, match="not found"):
            fs.update_sync_state(
                "test-proj", "teams", "teams-general",
                {"unprocessed_count": 1},
            )

    def test_add_sync_source_teams_missing_channel_id_raises(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="channel_id"):
            fs.add_sync_source("test-proj", "teams", id="t1", label="T1")

    def test_add_sync_source_outlook_missing_folder_id_raises(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="folder_id"):
            fs.add_sync_source("test-proj", "outlook", id="o1", label="O1")

    def test_add_sync_source_sharepoint_missing_fields_raises(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        with pytest.raises(ValueError, match="site_url"):
            fs.add_sync_source("test-proj", "sharepoint", id="sp1", label="SP1")


class TestM365RefParser:
    """TestM365RefParser — all token types, with/without path, malformed refs."""

    def test_sp_ref_no_path(self):
        result = parse_refs("See [sp:sp-contracts]")
        assert len(result["m365_refs"]) == 1
        r = result["m365_refs"][0]
        assert r.type == "sp"
        assert r.source_id == "sp-contracts"
        assert r.path is None

    def test_sp_ref_with_path(self):
        result = parse_refs("See [sp:sp-contracts/msa-v2.pdf]")
        assert len(result["m365_refs"]) == 1
        r = result["m365_refs"][0]
        assert r.type == "sp"
        assert r.source_id == "sp-contracts"
        assert r.path == "msa-v2.pdf"

    def test_sp_ref_with_nested_path(self):
        result = parse_refs("From [sp:sp-contracts/folder/sub/file.pdf]")
        r = result["m365_refs"][0]
        assert r.path == "folder/sub/file.pdf"

    def test_tm_ref_no_message(self):
        result = parse_refs("Channel [tm:teams-general]")
        r = result["m365_refs"][0]
        assert r.type == "tm"
        assert r.source_id == "teams-general"
        assert r.message_id is None

    def test_tm_ref_with_message_id(self):
        result = parse_refs("Message [tm:teams-general/123456789]")
        r = result["m365_refs"][0]
        assert r.type == "tm"
        assert r.message_id == "123456789"

    def test_ol_ref_no_message(self):
        result = parse_refs("Thread [ol:outlook-internal]")
        r = result["m365_refs"][0]
        assert r.type == "ol"
        assert r.source_id == "outlook-internal"

    def test_ol_ref_with_message_id(self):
        result = parse_refs("Email [ol:outlook-internal/AAMkAGI2]")
        r = result["m365_refs"][0]
        assert r.type == "ol"
        assert r.message_id == "AAMkAGI2"

    def test_multiple_refs_in_content(self):
        content = "See [sp:sp-contracts/file.pdf] and [tm:teams-general]"
        result = parse_refs(content)
        assert len(result["m365_refs"]) == 2
        types = {r.type for r in result["m365_refs"]}
        assert types == {"sp", "tm"}

    def test_duplicate_refs_deduplicated(self):
        content = "[sp:sp-contracts] and [sp:sp-contracts]"
        result = parse_refs(content)
        assert len(result["m365_refs"]) == 1

    def test_malformed_ref_skipped(self):
        # Should not raise, just produce no m365_refs
        result = parse_refs("Bad ref [xx:something] and normal text")
        assert result["m365_refs"] == []

    def test_existing_refs_still_parsed(self):
        content = "@john-doe #python [sp:sp-contracts]"
        result = parse_refs(content)
        assert "john-doe" in result["refs"]
        assert "python" in result["tags"]
        assert len(result["m365_refs"]) == 1

    def test_double_bracket_links_not_affected(self):
        # [[wiki-links]] should not be parsed as m365 refs
        content = "[[project-slug]] and [sp:sp-contracts]"
        result = parse_refs(content)
        assert "project-slug" in result["links"]
        assert len(result["m365_refs"]) == 1


class TestInternalRefParser:
    """TestInternalRefParser — [mem:path] token parsing via parse_refs."""

    def test_single_mem_ref(self):
        result = parse_refs("See [mem:projects/acme/knowledge/contract.md]")
        assert len(result["internal_refs"]) == 1
        assert result["internal_refs"][0].path == "projects/acme/knowledge/contract.md"

    def test_nested_path(self):
        result = parse_refs("From [mem:projects/acme/correspondence/q1-thread.md]")
        assert result["internal_refs"][0].path == "projects/acme/correspondence/q1-thread.md"

    def test_multiple_mem_refs(self):
        content = "[mem:projects/a/notes/x.md] and [mem:projects/b/knowledge/y.md]"
        result = parse_refs(content)
        paths = [r.path for r in result["internal_refs"]]
        assert "projects/a/notes/x.md" in paths
        assert "projects/b/knowledge/y.md" in paths

    def test_duplicate_mem_refs_deduplicated(self):
        content = "[mem:projects/a/notes/x.md] and [mem:projects/a/notes/x.md]"
        result = parse_refs(content)
        assert len(result["internal_refs"]) == 1

    def test_empty_mem_ref_skipped(self):
        result = parse_refs("[mem:]")
        assert result["internal_refs"] == []

    def test_whitespace_stripped(self):
        result = parse_refs("[mem: projects/a/notes/x.md ]")
        assert result["internal_refs"][0].path == "projects/a/notes/x.md"

    def test_coexists_with_m365_and_at_refs(self):
        content = "@john-doe [sp:sp-contracts] [mem:projects/a/notes/x.md] #legal"
        result = parse_refs(content)
        assert "john-doe" in result["refs"]
        assert "legal" in result["tags"]
        assert len(result["m365_refs"]) == 1
        assert len(result["internal_refs"]) == 1

    def test_double_bracket_links_not_parsed_as_mem(self):
        # [[link]] must not match [mem:]
        content = "[[some-link]] and [mem:projects/a/notes/x.md]"
        result = parse_refs(content)
        assert "some-link" in result["links"]
        assert len(result["internal_refs"]) == 1


class TestRefsIndexM365:
    """TestRefsIndexM365 — m365_refs indexed on write, lazy migration on read."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_m365_refs_indexed_on_write(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [sp:sp-contracts/file.pdf]",
        )
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert len(entry.m365_refs) == 1
        assert entry.m365_refs[0].source_id == "sp-contracts"

    def test_m365_refs_lazy_migration(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        # Write a refs-index entry without m365_refs field (simulating old data)
        old_data = {
            "entries": {
                "projects/test-proj/notes/note.md": {
                    "path": "projects/test-proj/notes/note.md",
                    "refs": [],
                    "tags": ["old-tag"],
                    "links": [],
                }
            }
        }
        (fs.root / "_refs-index.json").write_text(
            json.dumps(old_data), encoding="utf-8"
        )
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert entry.m365_refs == []
        assert "old-tag" in entry.tags

    def test_rebuild_refs_index_includes_m365_refs(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nFrom [ol:outlook-internal/msg123]",
        )
        # Wipe index
        (fs.root / "_refs-index.json").write_text('{"entries": {}}', encoding="utf-8")
        fs.rebuild_refs_index()
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert len(entry.m365_refs) == 1
        assert entry.m365_refs[0].type == "ol"

    def test_get_refs_for_m365_source_id(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [sp:sp-contracts/file.pdf]",
        )
        results = fs.get_refs_for("sp-contracts")
        assert "projects/test-proj/notes/note.md" in results


class TestInternalRefsIndex:
    """TestInternalRefsIndex — internal_refs indexed on write, lazy migration, get_refs_for, warnings."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_internal_refs_indexed_on_write(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nRelated: [mem:projects/test-proj/knowledge/context.md]",
        )
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert len(entry.internal_refs) == 1
        assert entry.internal_refs[0].path == "projects/test-proj/knowledge/context.md"

    def test_internal_refs_lazy_migration(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        # Write a refs-index entry without internal_refs field (simulating old data)
        old_data = {
            "entries": {
                "projects/test-proj/notes/note.md": {
                    "path": "projects/test-proj/notes/note.md",
                    "refs": [],
                    "tags": ["old-tag"],
                    "links": [],
                    "m365_refs": [],
                }
            }
        }
        (fs.root / "_refs-index.json").write_text(
            json.dumps(old_data), encoding="utf-8"
        )
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert entry.internal_refs == []
        assert "old-tag" in entry.tags

    def test_rebuild_refs_index_includes_internal_refs(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nBased on [mem:projects/test-proj/knowledge/context.md]",
        )
        # Wipe index
        (fs.root / "_refs-index.json").write_text('{"entries": {}}', encoding="utf-8")
        fs.rebuild_refs_index()
        index = fs.load_refs_index()
        entry = index.entries.get("projects/test-proj/notes/note.md")
        assert entry is not None
        assert len(entry.internal_refs) == 1
        assert entry.internal_refs[0].path == "projects/test-proj/knowledge/context.md"

    def test_get_refs_for_by_internal_ref_exact_path(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        results = fs.get_refs_for("projects/test-proj/knowledge/context.md")
        assert "projects/test-proj/notes/note.md" in results

    def test_get_refs_for_by_internal_ref_filename(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        results = fs.get_refs_for("context.md")
        assert "projects/test-proj/notes/note.md" in results

    def test_warn_unresolved_internal_ref_when_target_missing(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        warnings = fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/missing.md]",
        )
        assert any("missing.md" in w for w in warnings)
        assert any("[mem:" in w for w in warnings)

    def test_no_warning_when_internal_ref_target_exists(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        # First create the target file
        fs.write_file(
            "projects/test-proj/knowledge/context.md",
            "---\nsource: null\nprocessed: null\n---\n\n# Context",
        )
        # Now reference it
        warnings = fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        assert not any("[mem:" in w for w in warnings)


class TestGetRelatedFiles:
    """TestGetRelatedFiles — bidirectional [mem:] cross-reference map."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_referenced_by_lists_files_that_link_here(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        # Create the target file
        fs.write_file(
            "projects/test-proj/knowledge/context.md",
            "---\nsource: null\nprocessed: null\n---\n\n# Context",
        )
        # Create a file that references the target
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        result = fs.get_related_files("projects/test-proj/knowledge/context.md")
        assert "projects/test-proj/notes/note.md" in result["referenced_by"]

    def test_references_lists_files_this_file_links_to(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/knowledge/context.md",
            "---\nsource: null\nprocessed: null\n---\n\n# Context",
        )
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        result = fs.get_related_files("projects/test-proj/notes/note.md")
        assert "projects/test-proj/knowledge/context.md" in result["references"]

    def test_bidirectional_links(self, fs):
        """Two files that reference each other should appear in each other's maps."""
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/knowledge/context.md",
            "---\nsource: null\nprocessed: null\n---\n\n# Context\n[mem:projects/test-proj/notes/note.md]",
        )
        fs.write_file(
            "projects/test-proj/notes/note.md",
            "# Note\n\nSee [mem:projects/test-proj/knowledge/context.md]",
        )
        r_ctx = fs.get_related_files("projects/test-proj/knowledge/context.md")
        r_note = fs.get_related_files("projects/test-proj/notes/note.md")
        assert "projects/test-proj/notes/note.md" in r_ctx["referenced_by"]
        assert "projects/test-proj/knowledge/context.md" in r_note["referenced_by"]

    def test_m365_refs_included_in_result(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file(
            "projects/test-proj/knowledge/contract.md",
            "---\nsource: '[sp:sp-contracts/msa-v2.pdf]'\nprocessed: null\n---\n\n# Contract\n\nSee [sp:sp-contracts/msa-v2.pdf]",
        )
        result = fs.get_related_files("projects/test-proj/knowledge/contract.md")
        assert len(result["m365_refs"]) == 1
        assert result["m365_refs"][0]["source_id"] == "sp-contracts"

    def test_empty_result_for_file_with_no_cross_refs(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.write_file("projects/test-proj/notes/standalone.md", "# Standalone note")
        result = fs.get_related_files("projects/test-proj/notes/standalone.md")
        assert result["referenced_by"] == []
        assert result["references"] == []
        assert result["m365_refs"] == []

    def test_nonexistent_file_returns_empty_result(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        result = fs.get_related_files("projects/test-proj/notes/nonexistent.md")
        assert result["referenced_by"] == []
        assert result["references"] == []
        assert result["m365_refs"] == []

    def test_mcp_tool_get_related_files(self, tmp_path):
        server = create_server(tmp_path)

        def call(tool, **kwargs):
            return asyncio.run(server.call_tool(tool, kwargs))

        call("create_project", slug="rel-proj", name="Rel")
        call(
            "write_file",
            path="projects/rel-proj/knowledge/context.md",
            content="---\nsource: null\nprocessed: null\n---\n\n# Context",
        )
        call(
            "write_file",
            path="projects/rel-proj/notes/note.md",
            content="# Note\n\nSee [mem:projects/rel-proj/knowledge/context.md]",
        )
        r = parse_result(
            call("get_related_files", path="projects/rel-proj/knowledge/context.md")
        )
        assert "error" not in r
        assert "projects/rel-proj/notes/note.md" in r["result"]["referenced_by"]

    def test_mcp_tool_get_related_files_not_found(self, tmp_path):
        server = create_server(tmp_path)

        def call(tool, **kwargs):
            return asyncio.run(server.call_tool(tool, kwargs))

        call("create_project", slug="rel-proj", name="Rel")
        r = parse_result(
            call("get_related_files", path="projects/rel-proj/notes/nonexistent.md")
        )
        # Non-existent file returns empty result, not an error
        assert "error" not in r
        assert r["result"]["referenced_by"] == []
        assert r["result"]["references"] == []


class TestResolveM365Ref:
    """TestResolveM365Ref — resolves registered source, errors on unknown."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_resolve_sp_ref(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "sharepoint", id="sp-contracts",
            label="Contracts library",
            site_url="https://company.sharepoint.com/sites/acme",
            library="Contracts",
        )
        result = fs.resolve_m365_ref("test-proj", "sp:sp-contracts/msa-v2.pdf")
        assert "error" not in result
        assert result["source_id"] == "sp-contracts"
        assert result["type"] == "sharepoint"
        assert result["path"] == "msa-v2.pdf"
        assert result["m365_available"] is False
        assert result["site_url"] == "https://company.sharepoint.com/sites/acme"

    def test_resolve_tm_ref(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General channel", channel_id="19:abc123",
        )
        result = fs.resolve_m365_ref("test-proj", "tm:teams-general/msg-456")
        assert "error" not in result
        assert result["type"] == "teams"
        assert result["message_id"] == "msg-456"
        assert result["m365_available"] is False

    def test_resolve_ol_ref(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "outlook", id="outlook-internal",
            label="Internal thread", folder_id="AAMkAGI2",
        )
        result = fs.resolve_m365_ref("test-proj", "ol:outlook-internal")
        assert "error" not in result
        assert result["type"] == "outlook"
        assert result["folder_id"] == "AAMkAGI2"

    def test_resolve_unknown_source_returns_error(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        result = fs.resolve_m365_ref("test-proj", "sp:unknown-source/file.pdf")
        assert "error" in result
        assert "not registered" in result["error"]

    def test_resolve_missing_sync_yaml_returns_error(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        # No _sync.yaml created
        result = fs.resolve_m365_ref("test-proj", "sp:sp-contracts/file.pdf")
        assert "error" in result
        assert "No M365 sources" in result["error"]

    def test_resolve_with_brackets(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "sharepoint", id="sp-contracts",
            label="Contracts library",
            site_url="https://company.sharepoint.com",
            library="Contracts",
        )
        # With brackets as they would appear in markdown
        result = fs.resolve_m365_ref("test-proj", "[sp:sp-contracts]")
        assert "error" not in result
        assert result["source_id"] == "sp-contracts"

    def test_resolve_detects_local_doc(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "sharepoint", id="sp-contracts",
            label="Contracts library",
            site_url="https://company.sharepoint.com",
            library="Contracts",
        )
        # Create local doc copy
        docs_dir = fs.root / "projects" / "test-proj" / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "msa-v2.pdf").write_bytes(b"PDF content")
        result = fs.resolve_m365_ref("test-proj", "sp:sp-contracts/msa-v2.pdf")
        assert result["local_doc"] is not None
        assert "msa-v2.pdf" in result["local_doc"]

    def test_resolve_detects_knowledge_entry(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "sharepoint", id="sp-contracts",
            label="Contracts library",
            site_url="https://company.sharepoint.com",
            library="Contracts",
        )
        # Write a knowledge entry referencing sp-contracts
        fs.write_file(
            "projects/test-proj/knowledge/contract-summary.md",
            "---\nsource: null\nprocessed: null\nmethod: null\nmodel: null\nprompt_ref: null\n---\n\n"
            "# Contract Summary\n\nSee [sp:sp-contracts/msa-v2.pdf]",
        )
        result = fs.resolve_m365_ref("test-proj", "sp:sp-contracts/msa-v2.pdf")
        assert result["knowledge_entry"] is not None
        assert "contract-summary" in result["knowledge_entry"]


class TestListDueForSync:
    """TestListDueForSync — overdue detection, manual never returned, disabled skipped."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_never_processed_is_overdue(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        results = fs.list_projects_due_for_sync()
        assert any(r["slug"] == "test-proj" for r in results)

    def test_recently_processed_not_overdue(self, fs):
        from datetime import datetime, timezone

        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        # Just processed
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fs.update_sync_state(
            "test-proj", "teams", "teams-general",
            {"last_processed_at": now_str},
        )
        results = fs.list_projects_due_for_sync()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_disabled_source_not_included(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-disabled",
            label="Disabled", channel_id="19:abc", enabled=False,
        )
        results = fs.list_projects_due_for_sync()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_no_sync_yaml_not_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        results = fs.list_projects_due_for_sync()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_manual_frequency_never_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-manual",
            label="Manual", channel_id="19:abc",
        )
        # Set correspondence_frequency to manual
        raw = fs._load_sync_state_raw("test-proj")
        raw["pipeline"]["correspondence_frequency"] = "manual"
        fs._save_sync_state_raw("test-proj", raw)
        results = fs.list_projects_due_for_sync()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_list_due_returns_overdue_source_metadata(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        results = fs.list_projects_due_for_sync()
        project = next((r for r in results if r["slug"] == "test-proj"), None)
        assert project is not None
        assert len(project["overdue_sources"]) == 1
        src = project["overdue_sources"][0]
        assert src["id"] == "teams-general"
        assert src["type"] == "teams"
        assert src["label"] == "General"


class TestListDueForSynthesis:
    """Tests for list_projects_due_for_synthesis."""

    @pytest.fixture
    def fs(self, tmp_path):
        memory_fs = MemoryFS(tmp_path)
        memory_fs.initialise()
        return memory_fs

    def test_overdue_synthesis_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        # Set next_knowledge_synthesis to past date
        fs.update_sync_state("test-proj", "pipeline", "", {
            "next_knowledge_synthesis": "2020-01-01",
        })
        results = fs.list_projects_due_for_synthesis()
        assert any(r["slug"] == "test-proj" for r in results)

    def test_future_synthesis_not_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        fs.update_sync_state("test-proj", "pipeline", "", {
            "next_knowledge_synthesis": "2099-12-31",
        })
        results = fs.list_projects_due_for_synthesis()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_null_synthesis_not_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        fs.add_sync_source(
            "test-proj", "teams", id="teams-general",
            label="General", channel_id="19:abc",
        )
        results = fs.list_projects_due_for_synthesis()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs

    def test_no_sync_yaml_not_returned(self, fs):
        fs.scaffold_project("test-proj", make_meta())
        results = fs.list_projects_due_for_synthesis()
        slugs = [r["slug"] for r in results]
        assert "test-proj" not in slugs


class TestM365GuideResource:
    """TestM365GuideResource — resource exists, contains all section headings."""

    _REQUIRED_HEADINGS = [
        "## M365 availability model",
        "## M365 reference syntax",
        "## Source registry",
        "## Sync state tools",
        "## _sync.yaml schema",
        "## Pipeline integration note",
    ]

    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_m365_resource_exists(self, mcp_server):
        resources = asyncio.run(mcp_server.list_resources())
        uris = [str(r.uri) for r in resources]
        assert "memory://m365" in uris

    def test_m365_resource_contains_all_sections(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://m365"))
        text = result.contents[0].content
        for heading in self._REQUIRED_HEADINGS:
            assert heading in text, f"Missing section heading: {heading!r}"

    def test_m365_resource_is_string(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://m365"))
        assert isinstance(result.contents[0].content, str)
        assert len(result.contents[0].content) > 100

    def test_m365_resource_source_registry_empty_by_default(self, mcp_server):
        result = asyncio.run(mcp_server.read_resource("memory://m365"))
        text = result.contents[0].content
        assert "No M365 sources registered" in text

    def test_m365_resource_source_registry_shows_live_sources(self, mcp_server):
        self._call(
            mcp_server, "create_project", slug="m365-proj", name="M365 Test"
        )
        self._call(
            mcp_server, "add_sync_source",
            project_slug="m365-proj",
            source_type="teams",
            id="teams-general",
            label="General channel",
            channel_id="19:abc123",
        )
        result = asyncio.run(mcp_server.read_resource("memory://m365"))
        text = result.contents[0].content
        assert "m365-proj" in text
        assert "teams-general" in text

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestSyncYamlProtections:
    """_sync.yaml must be protected from direct write, read, and delete."""

    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_write_file_blocks_sync_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="prot-proj", name="Prot")
        r = parse_result(
            self._call(
                mcp_server,
                "write_file",
                path="projects/prot-proj/_sync.yaml",
                content="bad content",
            )
        )
        assert "error" in r
        assert "_sync.yaml" in r["error"]

    def test_read_file_blocks_sync_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="prot-proj", name="Prot")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="prot-proj",
            source_type="teams",
            id="t1",
            label="T1",
            channel_id="19:abc",
        )
        r = parse_result(
            self._call(mcp_server, "read_file", path="projects/prot-proj/_sync.yaml")
        )
        assert "error" in r
        assert "_sync.yaml" in r["error"]

    def test_delete_file_blocks_sync_yaml(self, mcp_server):
        self._call(mcp_server, "create_project", slug="prot-proj", name="Prot")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="prot-proj",
            source_type="teams",
            id="t1",
            label="T1",
            channel_id="19:abc",
        )
        r = parse_result(
            self._call(mcp_server, "delete_file", path="projects/prot-proj/_sync.yaml")
        )
        assert "error" in r

    def test_sync_yaml_not_in_manifest(self, mcp_server):
        self._call(mcp_server, "create_project", slug="prot-proj", name="Prot")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="prot-proj",
            source_type="teams",
            id="t1",
            label="T1",
            channel_id="19:abc",
        )
        # Rebuild manifest and check _sync.yaml not included
        self._call(mcp_server, "update_manifest", folder_path="projects/prot-proj")
        manifest_result = parse_result(
            self._call(mcp_server, "get_folder_manifest", folder_path="projects/prot-proj")
        )
        assert "_sync.yaml" not in manifest_result["result"]

    def test_search_files_skips_sync_yaml(self, mcp_server):
        # search_files only searches .md files, so _sync.yaml is already excluded
        self._call(mcp_server, "create_project", slug="prot-proj", name="Prot")
        r = parse_result(
            self._call(mcp_server, "search_files", keyword="yaml", project_slug="prot-proj")
        )
        assert "error" not in r
        # No _sync.yaml results (it's yaml, not md)
        if r["result"]:
            for hit in r["result"]:
                assert "_sync.yaml" not in hit["path"]

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)


class TestMCPSyncStateTools:
    """Integration tests for MCP sync state tools."""

    def _call(self, server, tool: str, **kwargs):
        return asyncio.run(server.call_tool(tool, kwargs))

    def test_get_sync_state_missing(self, mcp_server):
        self._call(mcp_server, "create_project", slug="sync-proj", name="Sync")
        r = parse_result(self._call(mcp_server, "get_sync_state", project_slug="sync-proj"))
        assert "error" not in r
        assert r["result"] is None
        assert "No sync state found" in r["warnings"]

    def test_add_sync_source_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="sync-proj", name="Sync")
        r = parse_result(
            self._call(
                mcp_server, "add_sync_source",
                project_slug="sync-proj",
                source_type="teams",
                id="teams-general",
                label="General channel",
                channel_id="19:abc123",
            )
        )
        assert "error" not in r
        assert r["result"]["id"] == "teams-general"

    def test_add_sync_source_invalid_type(self, mcp_server):
        self._call(mcp_server, "create_project", slug="sync-proj", name="Sync")
        r = parse_result(
            self._call(
                mcp_server, "add_sync_source",
                project_slug="sync-proj",
                source_type="invalid",
                id="x",
                label="X",
            )
        )
        assert "error" in r

    def test_update_sync_state_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="sync-proj", name="Sync")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="sync-proj",
            source_type="teams",
            id="teams-general",
            label="General",
            channel_id="19:abc",
        )
        r = parse_result(
            self._call(
                mcp_server, "update_sync_state",
                project_slug="sync-proj",
                source_type="teams",
                source_id="teams-general",
                fields={"last_processed_at": "2025-03-28T06:00:00Z"},
            )
        )
        assert "error" not in r
        assert r["result"]["last_processed_at"] == "2025-03-28T06:00:00Z"

    def test_list_projects_due_for_sync_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="sync-proj", name="Sync")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="sync-proj",
            source_type="teams",
            id="teams-general",
            label="General",
            channel_id="19:abc",
        )
        r = parse_result(self._call(mcp_server, "list_projects_due_for_sync"))
        assert "error" not in r
        slugs = [p["slug"] for p in r["result"]]
        assert "sync-proj" in slugs

    def test_list_projects_due_for_synthesis_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="synth-proj", name="Synth")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="synth-proj",
            source_type="teams",
            id="t1",
            label="T1",
            channel_id="19:abc",
        )
        self._call(
            mcp_server, "update_sync_state",
            project_slug="synth-proj",
            source_type="pipeline",
            source_id="",
            fields={"next_knowledge_synthesis": "2020-01-01"},
        )
        r = parse_result(self._call(mcp_server, "list_projects_due_for_synthesis"))
        assert "error" not in r
        slugs = [p["slug"] for p in r["result"]]
        assert "synth-proj" in slugs

    def test_resolve_m365_ref_tool(self, mcp_server):
        self._call(mcp_server, "create_project", slug="ref-proj", name="Ref")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="ref-proj",
            source_type="sharepoint",
            id="sp-contracts",
            label="Contracts library",
            site_url="https://company.sharepoint.com/sites/acme",
            library="Contracts",
        )
        r = parse_result(
            self._call(
                mcp_server, "resolve_m365_ref",
                project_slug="ref-proj",
                ref="sp:sp-contracts/msa-v2.pdf",
            )
        )
        assert "error" not in r
        assert r["result"]["source_id"] == "sp-contracts"
        assert r["result"]["m365_available"] is False

    def test_get_project_context_deep_includes_sync(self, mcp_server):
        self._call(mcp_server, "create_project", slug="deep-sync-proj", name="Deep Sync")
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="deep-sync-proj", deep=True)
        )
        assert "error" not in r
        assert "sync" in r["result"]
        assert r["result"]["sync"] is None  # No _sync.yaml yet

    def test_get_project_context_deep_includes_sync_content(self, mcp_server):
        self._call(mcp_server, "create_project", slug="deep-sync2-proj", name="Deep Sync 2")
        self._call(
            mcp_server, "add_sync_source",
            project_slug="deep-sync2-proj",
            source_type="teams",
            id="teams-general",
            label="General",
            channel_id="19:abc",
        )
        r = parse_result(
            self._call(mcp_server, "get_project_context", slug="deep-sync2-proj", deep=True)
        )
        assert "error" not in r
        assert r["result"]["sync"] is not None
        assert "sources" in r["result"]["sync"]

    @pytest.fixture
    def mcp_server(self, tmp_path):
        return create_server(tmp_path)
