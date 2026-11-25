"""Load the same operating guide for CLI and MCP clients."""

from importlib.resources import files

GUIDE_URI = "ninjatap://guide"


def read_guide() -> str:
    return files("ninjatap").joinpath("guide.md").read_text(encoding="utf-8")
