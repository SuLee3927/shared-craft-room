from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.server import TOOLS, app, handle_mcp


def test_server_exposes_only_craft_routes():
    paths = {route.path for route in app.routes}
    assert "/api/{access_key}/canvas" in paths
    assert "/api/{access_key}/bead-boards" in paths
    assert "/api/{access_key}/gallery" in paths
    assert not any("entries" in path or "timeline" in path or "trash" in path for path in paths)


def test_mcp_lists_only_craft_tools():
    response = handle_mcp("alice", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {tool["name"] for tool in TOOLS}
    assert "write_entry" not in names
