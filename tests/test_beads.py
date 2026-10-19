from io import BytesIO
import base64
from pathlib import Path
import sys

from PIL import Image
import pytest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.beads import BeadBoards


def test_place_and_take_are_physical_actions(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "小猫", "together", 16)
    result = store.place("lee", board["id"], [{"x": 2, "y": 3, "color": "#f4c7cf"}])
    assert result["bead_count"] == 1
    state = store.get("du", board["id"])
    assert state["cells"]["2,3"]["actor"] == "lee"
    assert state["cells"]["2,3"]["code"] == "F14"
    assert state["activity"]["actor"] == "lee"
    assert state["activity"]["action"] == "place"
    assert state["activity"]["color"] == "#ffa9ad"
    assert state["palette"][1]["name"] == "浅粉红"
    assert state["inventories"]["lee"]["#ffa9ad"] == 79
    assert store.take("lee", board["id"], 2, 3)["bead_count"] == 0
    assert store.get("lee", board["id"])["inventories"]["lee"]["#ffa9ad"] == 80


def test_color_selection_and_aliases_are_shared(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "选色", "together", 16)
    assert store.select_color("du", board["id"], "F7")["selected"] == "#971937"
    state = store.get("lee", board["id"])
    assert state["selections"]["du"] == "#971937"
    assert state["activity"]["action"] == "select"
    store.place("du", board["id"], [{"x": 1, "y": 1, "color": "深红"}])
    store.place("du", board["id"], [{"x": 2, "y": 1, "color": "#971937"}])
    assert store.get("lee", board["id"])["cells"]["2,1"]["code"] == "F7"


def test_board_presence_tracks_view_selection_placing_and_expiry(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "一起拼", "together", 16)
    store.get("du", board["id"])
    assert store.presence_for("lee", board["id"])[0]["action"] == "viewing"
    store.select_color("du", board["id"], "F7")
    assert store.presence_for("lee", board["id"])[0]["action"] == "selecting"
    store.place("du", board["id"], [{"x": 1, "y": 1, "color": "F7"}])
    assert store.presence_for("lee", board["id"])[0]["action"] == "placing"
    store.presence[(board["id"], "du")]["seen"] -= 301
    assert store.presence_for("lee", board["id"]) == []


def test_work_plan_survives_turns_and_tracks_handfuls(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("du", "续作", "together", 16)
    steps = [{"x": x, "y": 2, "color": "F14"} for x in range(7)]
    store.set_work_plan("du", board["id"], steps, "一排粉豆")
    opened = store.get("du", board["id"])
    assert len(opened["work_session"]["remaining"]) == 7
    assert opened["reference_image"].startswith("data:image/png;base64,")
    result = store.place("du", board["id"], steps[:5])
    assert result["work_remaining"] == 2
    resumed = store.get("du", board["id"])["work_session"]
    assert resumed["title"] == "一排粉豆"
    store.place("du", board["id"], steps[5:])
    assert store.get("du", board["id"])["work_session"] is None


@pytest.mark.parametrize("size", [8, 12, 16, 24, 32, 48, 64])
def test_supported_board_sizes(tmp_path, size):
    store = BeadBoards(tmp_path / f"beads-{size}.json")
    board = store.create("lee", f"{size} 格豆板", "together", size)
    assert board["size"] == size


def test_handful_limit_and_hidden_gift(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("du", "礼物", "gift", 16)
    assert store.list_boards("lee") == []
    with pytest.raises(ValueError, match="1 to 5"):
        store.place("du", board["id"], [{"x": x, "y": 0, "color": "#ffffff"} for x in range(6)])
    revealed = store.reveal("du", board["id"])
    assert revealed["revision"] == 1
    assert store.list_boards("lee")[0]["title"] == "礼物"


def test_only_owner_can_delete_board(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "准备拆掉", "together", 16)
    with pytest.raises(ValueError, match="only the person"):
        store.delete("du", board["id"])
    assert store.delete("lee", board["id"])["deleted"] is True
    assert store.list_boards("lee") == []


def test_exhausted_color_can_be_refilled_by_one_bag(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "补豆测试", "together", 16)
    data = store._load()
    saved = store._find(data, board["id"])
    store._inventory(saved, "lee")["#ffa9ad"] = 0
    store._save(data)
    result = store.refill("lee", board["id"], "#ffa9ad")
    assert result["refilled"] == 80
    assert store.get("lee", board["id"])["inventories"]["lee"]["#ffa9ad"] == 80
    with pytest.raises(ValueError, match="open bag"):
        store.refill("lee", board["id"], "#ffa9ad")


def test_board_png(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "图", "together", 16)
    store.place("lee", board["id"], [{"x": 0, "y": 0, "color": "#ed7359"}])
    image = Image.open(BytesIO(store.png_bytes("lee", board["id"])))
    assert image.width == image.height
    assert image.width > 500


def test_ironing_workflow_and_quality(tmp_path):
    store = BeadBoards(tmp_path / "beads.json")
    board = store.create("lee", "爱心", "together", 16)
    store.place("lee", board["id"], [{"x": 3, "y": 4, "color": "#ffa9ad"}])
    with patch("shared_craft_room.beads.unix_now", side_effect=[100, 100, 101, 101, 106, 106, 110, 110, 114, 114]):
        assert store.craft("lee", board["id"], "cover")["stage"] == "covered"
        heated = store.craft("du", board["id"], "heat")
        assert heated["stage"] == "heating"
        assert store.craft("du", board["id"], "start_iron")["stage"] == "ironing"
        ironed = store.craft("du", board["id"], "finish_iron")
        assert ironed["craft"]["quality"] == "good"
        assert ironed["craft"]["actual_iron_seconds"] == 4
        assert store.craft("lee", board["id"], "lift")["stage"] == "finished"
    activity = store.get("du", board["id"])["activity"]
    assert activity["actor"] == "lee"
    assert activity["action"] == "craft"
    assert activity["craft_action"] == "lift"
    with pytest.raises(ValueError, match="ironing paper"):
        store.place("lee", board["id"], [{"x": 4, "y": 4, "color": "#ffa9ad"}])
    image = Image.new("RGB", (20, 20), "pink")
    output = BytesIO()
    image.save(output, "PNG")
    encoded = base64.b64encode(output.getvalue()).decode()
    assert store.save_decoration("lee", board["id"], f"data:image/png;base64,{encoded}")["decorated"] is True
    assert store.decorated_bytes("du", board["id"]).startswith(b"\x89PNG")
