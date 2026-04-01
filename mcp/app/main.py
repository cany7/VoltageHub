from __future__ import annotations

import sys
from pathlib import Path


def _prefer_workspace_core() -> None:
    """Prefer the sibling workspace package during local `uv run` development."""

    repo_root = Path.cwd().resolve().parent
    core_path = repo_root / "voltage_hub_core"
    if core_path.exists():
        repo_root_text = str(repo_root)
        if repo_root_text not in sys.path:
            sys.path.insert(0, repo_root_text)


_prefer_workspace_core()

from app.adapters.voltagehub import VoltageHubMCPAdapter, resource_specs, tool_specs
from app.config.runtime import create_runtime


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on installed extras
        raise RuntimeError(
            "The `mcp` package is required to run voltagehub-mcp. "
            "Install the dependencies for the mcp package before starting the server."
        ) from exc

    runtime = create_runtime()
    adapter = VoltageHubMCPAdapter(runtime)
    server = FastMCP("VoltageHub")

    for spec in tool_specs(adapter):
        server.tool(name=spec.name, description=spec.description)(spec.handler)

    for spec in resource_specs(adapter):
        server.resource(spec.uri, name=spec.name, description=spec.description)(spec.handler)

    return server


def main() -> None:
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
