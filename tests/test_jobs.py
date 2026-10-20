from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.beads import BeadBoards
from shared_craft_room.canvas import SharedCanvas
from shared_craft_room.jobs import CraftJobs


def wait_for(jobs, actor, job_id):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = jobs.status(actor, job_id)
        if state["status"] in {"completed", "failed"}:
            return state
        time.sleep(.03)
    raise AssertionError("background craft job did not finish")


def test_canvas_sequence_draws_distinct_live_strokes(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    jobs = CraftJobs(canvas, BeadBoards(tmp_path / "beads.json"))
    queued = jobs.queue_canvas("assistant", [
        {"points": [{"x": 20, "y": 20}, {"x": 80, "y": 70}], "color": "#cc6688"},
        {"points": [{"x": 90, "y": 80}, {"x": 140, "y": 130}], "color": "#334455"},
    ], 180)
    finished = wait_for(jobs, "assistant", queued["job_id"])
    assert finished["status"] == "completed"
    assert finished["completed"] == 2
    assert len(canvas.state()["strokes"]) == 2


def test_canvas_sequence_is_published_gradually(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    jobs = CraftJobs(canvas, BeadBoards(tmp_path / "beads.json"))
    queued = jobs.queue_canvas("assistant", [
        {"points": [{"x": 10 + offset, "y": 20}, {"x": 40 + offset, "y": 60}]}
        for offset in (0, 100, 200)
    ], 400)
    time.sleep(.12)
    visible_mid_job = len(canvas.state()["strokes"])
    assert 1 <= visible_mid_job < 3
    assert wait_for(jobs, "assistant", queued["job_id"])["status"] == "completed"


def test_bead_plan_continues_in_color_accurate_handfuls(tmp_path):
    beads = BeadBoards(tmp_path / "beads.json")
    canvas = SharedCanvas(tmp_path / "canvas.json")
    jobs = CraftJobs(canvas, beads)
    board = beads.create("assistant", "queued", "together", 16)
    plan = [
        *({"x": x, "y": 1, "color": "F14"} for x in range(6)),
        *({"x": x, "y": 2, "color": "F7"} for x in range(4)),
    ]
    beads.set_work_plan("assistant", board["id"], plan)
    queued = jobs.continue_bead_plan("assistant", board["id"], handfuls=3, interval_ms=250)
    finished = wait_for(jobs, "assistant", queued["job_id"])
    assert finished["status"] == "completed"
    assert finished["completed"] == 10
    assert len(beads.get("assistant", board["id"])["cells"]) == 10


def test_job_status_is_actor_scoped(tmp_path):
    jobs = CraftJobs(SharedCanvas(tmp_path / "canvas.json"), BeadBoards(tmp_path / "beads.json"))
    queued = jobs.queue_canvas("assistant", [{"points": [{"x": 1, "y": 1}]}])
    try:
        jobs.status("human", queued["job_id"])
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("another participant could inspect a private job")
