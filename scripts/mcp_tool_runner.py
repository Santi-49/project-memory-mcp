"""CLI helper to call Project Memory MCP tools directly.

Examples:
  python scripts/mcp_tool_runner.py call --tool get_folder_manifest --params '{"folder_path":"projects/databuddy/updates"}'

  python scripts/mcp_tool_runner.py append-manifest-check \
      --project databuddy \
      --filename 003-final-test.md \
      --content "\n## Final test\n" \
      --iterations 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

# Allow running from repository root without package installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from server import create_server  # noqa: E402
import filesystem  # noqa: E402
import server  # noqa: E402


def _parse_result(tool_result: Any) -> dict[str, Any]:
    return json.loads(tool_result.content[0].text)


def _extract_manifest_filenames(rendered_manifest: str) -> list[str]:
    # Rendered blocks look like: ### `file-name.md`
    return re.findall(r"^### `([^`]+)`$", rendered_manifest, flags=re.MULTILINE)


async def call_tool(root: Path, tool: str, params: dict[str, Any]) -> dict[str, Any]:
    server = create_server(root)
    result = await server.call_tool(tool, params)
    return _parse_result(result)


async def run_generic_call(args: argparse.Namespace) -> int:
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        print(f"Invalid --params JSON: {exc}")
        return 2

    payload = await call_tool(args.root, args.tool, params)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if "error" not in payload else 1


async def run_append_manifest_check(args: argparse.Namespace) -> int:
    folder_path = f"projects/{args.project}/updates"
    file_path = f"{folder_path}/{args.filename}"
    exit_code = 0

    for i in range(1, args.iterations + 1):
        print(f"\n--- Iteration {i}/{args.iterations} ---")

        append_payload = await call_tool(
            args.root,
            "append_to_file",
            {"path": file_path, "content": args.content},
        )
        print("append_to_file:")
        print(json.dumps(append_payload, indent=2, ensure_ascii=False))
        if "error" in append_payload:
            exit_code = 1

        manifest_payload = await call_tool(
            args.root,
            "get_folder_manifest",
            {"folder_path": folder_path},
        )
        print("get_folder_manifest:")
        print(json.dumps(manifest_payload, indent=2, ensure_ascii=False))
        if "error" in manifest_payload:
            exit_code = 1
            continue

        rendered_manifest = manifest_payload.get("result", "")
        names = _extract_manifest_filenames(rendered_manifest)
        file_seen = args.filename in names
        print(f"manifest_files={names}")
        print(f"contains_{args.filename}={file_seen}")
        if not file_seen:
            exit_code = 1

        rebuild_payload = await call_tool(
            args.root,
            "update_manifest",
            {"folder_path": folder_path},
        )
        print("update_manifest:")
        print(json.dumps(rebuild_payload, indent=2, ensure_ascii=False))
        if "error" in rebuild_payload:
            exit_code = 1

    return exit_code


async def run_diagnose_manifest(args: argparse.Namespace) -> int:
    folder_path = args.folder
    folder_abs = args.root / Path(folder_path)
    index_abs = folder_abs / "_index.yaml"

    print("environment:")
    print(
        json.dumps(
            {
                "root": str(args.root.resolve()),
                "filesystem_module": str(Path(filesystem.__file__).resolve()),
                "server_module": str(Path(server.__file__).resolve()),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if index_abs.exists():
        print("raw_index_yaml:")
        print(index_abs.read_text(encoding="utf-8"))
    else:
        print(f"raw_index_yaml: missing at {index_abs}")

    payload = await call_tool(
        args.root, "get_folder_manifest", {"folder_path": folder_path}
    )
    print("rendered_manifest:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if "error" in payload:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Memory MCP tool runner")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "memory-root",
        help="Path to memory root (default: ./memory-root)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    call_cmd = sub.add_parser("call", help="Call any MCP tool once")
    call_cmd.add_argument("--tool", required=True, help="Tool name")
    call_cmd.add_argument(
        "--params",
        default="{}",
        help='Tool params as JSON object, e.g. {"folder_path":"projects/x/updates"}',
    )

    check_cmd = sub.add_parser(
        "append-manifest-check",
        help="Run append + get manifest + rebuild checks for updates folder",
    )
    check_cmd.add_argument("--project", required=True, help="Project slug")
    check_cmd.add_argument(
        "--filename", required=True, help="Updates file name, e.g. 003-final-test.md"
    )
    check_cmd.add_argument(
        "--content", required=True, help="Content to append each iteration"
    )
    check_cmd.add_argument(
        "--iterations", type=int, default=1, help="How many times to run the cycle"
    )

    diagnose_cmd = sub.add_parser(
        "diagnose-manifest",
        help="Print environment info plus raw and rendered manifest for a folder",
    )
    diagnose_cmd.add_argument(
        "--folder",
        required=True,
        help="Folder path relative to memory root, e.g. projects/databuddy/updates",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "call":
        return asyncio.run(run_generic_call(args))

    if args.command == "append-manifest-check":
        return asyncio.run(run_append_manifest_check(args))

    if args.command == "diagnose-manifest":
        return asyncio.run(run_diagnose_manifest(args))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
