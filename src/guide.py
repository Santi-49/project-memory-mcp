"""Serves the memory://guide and memory://m365 MCP resources.

These resources are read from static files in the skill/references/ directory,
which serves as the single source of truth for all server documentation.

To update the guides:
  - Edit skill/references/guide.md
  - Edit skill/references/m365-guide.md

The server always reads from these files; no code generation is needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fastmcp


def generate_guide(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Read and return the server guide from skill/references/guide.md.

    The guide is the single source of truth for server documentation.
    To update it, edit skill/references/guide.md directly.

    Never raises — returns a fallback string on error.
    """
    try:
        # Find skill/references relative to this file
        skill_dir = Path(__file__).parent.parent / "skill" / "references"
        guide_file = skill_dir / "guide.md"

        if guide_file.exists():
            return guide_file.read_text(encoding="utf-8")

        # Fallback if file not found
        return (
            f"# Project Memory MCP — Server Guide\n\n"
            f"_Could not load skill/references/guide.md_\n\n"
            f"The guide file should be present in skill/references/ directory.\n"
            f"Use list_projects to see available projects."
        )
    except Exception as exc:  # pragma: no cover
        return (
            f"# Project Memory MCP — Server Guide\n\n"
            f"_Error loading guide: {exc}_\n\n"
            f"Use list_projects to see available projects."
        )


def generate_m365_guide(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Read and return the M365 guide from skill/references/m365-guide.md.

    The M365 guide is the single source of truth for M365 integration documentation.
    To update it, edit skill/references/m365-guide.md directly.

    Never raises — returns a fallback string on error.
    """
    try:
        # Find skill/references relative to this file
        skill_dir = Path(__file__).parent.parent / "skill" / "references"
        m365_file = skill_dir / "m365-guide.md"

        if m365_file.exists():
            return m365_file.read_text(encoding="utf-8")

        # Fallback if file not found
        return (
            f"# Project Memory — M365 Integration Guide\n\n"
            f"_Could not load skill/references/m365-guide.md_\n\n"
            f"The M365 guide file should be present in skill/references/ directory.\n"
            f"Use get_sync_state to check M365 configuration for a specific project."
        )
    except Exception as exc:  # pragma: no cover
        return (
            f"# Project Memory — M365 Integration Guide\n\n"
            f"_Error loading M365 guide: {exc}_\n\n"
            f"Use get_sync_state to check M365 configuration for a specific project."
        )


def generate_skill_guide(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Read and return the skill guide from skill/SKILL.md.

    The skill guide is the single source of truth for pre-flight checklist and key rules.
    To update it, edit skill/SKILL.md directly.

    Never raises — returns a fallback string on error.
    """
    try:
        # Find skill/SKILL.md relative to this file
        skill_file = Path(__file__).parent.parent / "skill" / "SKILL.md"

        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")

        # Fallback if file not found
        return (
            f"# Project Memory MCP — Skill Guide\n\n"
            f"_Could not load skill/SKILL.md_\n\n"
            f"The skill guide should be present in the skill/ directory.\n"
            f"Read memory://guide and memory://m365 for server documentation."
        )
    except Exception as exc:  # pragma: no cover
        return (
            f"# Project Memory MCP — Skill Guide\n\n"
            f"_Error loading skill guide: {exc}_\n\n"
            f"Read memory://guide and memory://m365 for server documentation."
        )


def generate_new_project_setup(mcp: "fastmcp.FastMCP", root: Path) -> str:
    """Read and return the new project setup guide from skill/references/creating-new-project.md.

    This guide details the step-by-step process for initializing new projects.
    To update it, edit skill/references/creating-new-project.md directly.

    Never raises — returns a fallback string on error.
    """
    try:
        # Find skill/references relative to this file
        skill_dir = Path(__file__).parent.parent / "skill" / "references"
        setup_file = skill_dir / "creating-new-project.md"

        if setup_file.exists():
            return setup_file.read_text(encoding="utf-8")

        # Fallback if file not found
        return (
            f"# Initializing a New Project\n\n"
            f"_Could not load skill/references/creating-new-project.md_\n\n"
            f"The new project setup guide should be present in skill/references/ directory.\n"
            f"Start with create_project and follow the steps in memory://guide."
        )
    except Exception as exc:  # pragma: no cover
        return (
            f"# Initializing a New Project\n\n"
            f"_Error loading new project setup guide: {exc}_\n\n"
            f"Start with create_project and follow the steps in memory://guide."
        )
