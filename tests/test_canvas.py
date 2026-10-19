from io import BytesIO
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.canvas import SharedCanvas


def test_shared_canvas_draw_snapshot_and_actor_scoped_undo(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    first = canvas.draw_path("lee", [{"x": 10, "y": 10}, {"x": 100, "y": 80}], color="#cc6688", width=12)
    canvas.draw_path("du", [{"x": 30, "y": 50}, {"x": 200, "y": 120}], color="#334455", width=6)
    assert first["saved"] is True
    result = canvas.undo("lee")
    assert result["undone"] is True
    state = canvas.state()
    assert len(state["strokes"]) == 1
    assert state["strokes"][0]["actor"] == "du"
    image = Image.open(BytesIO(canvas.png_bytes()))
    assert image.size == (1200, 800)


def test_shared_canvas_rejects_out_of_bounds_points(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    try:
        canvas.draw_path("du", [{"x": -1, "y": 1}, {"x": 2, "y": 2}])
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("out of bounds stroke was accepted")


def test_shared_canvas_accepts_single_point_for_mobile_tap(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    result = canvas.draw_path("lee", [{"x": 60, "y": 40}], mode="erase", width=30)
    assert result["saved"] is True
    state = canvas.state()
    assert len(state["strokes"]) == 1
    assert state["strokes"][0]["points"] == [{"x": 60.0, "y": 40.0}]
    assert Image.open(BytesIO(canvas.png_bytes())).size == (1200, 800)


def test_shared_canvas_can_preserve_and_export_portrait_pages(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    canvas.clear("lee", width=800, height=1200)
    canvas.draw_path("lee", [{"x": 100, "y": 900}, {"x": 300, "y": 1100}])
    state = canvas.state()
    assert (state["width"], state["height"]) == (800, 1200)
    assert Image.open(BytesIO(canvas.png_bytes())).size == (800, 1200)


def test_shared_canvas_resize_keeps_visible_composition(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    canvas.draw_path("lee", [{"x": 600, "y": 400}])
    canvas.resize("lee", 800, 1200)
    state = canvas.state()
    assert state["strokes"][0]["points"] == [{"x": 400.0, "y": 600.0}]


def test_ai_path_is_naturalized_and_bucket_fill_is_saved(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    canvas.draw_path("du", [{"x": 10, "y": 10}, {"x": 110, "y": 10}], naturalize=True)
    points = canvas.state()["strokes"][0]["points"]
    assert len(points) == 3
    assert points[1]["y"] != 10
    canvas.draw_path("du", [{"x": 400, "y": 400}], color="#ed7359", mode="fill")
    assert canvas.state()["strokes"][-1]["mode"] == "fill"
    image = Image.open(BytesIO(canvas.png_bytes())).convert("RGB")
    assert image.getpixel((400, 400))[0] > image.getpixel((400, 400))[1]


def test_ai_closed_geometry_does_not_land_as_a_perfect_computed_shape(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    circle = []
    for index in range(33):
        angle = index / 32 * 6.283185307
        circle.append({"x": 400 + 150 * __import__('math').cos(angle), "y": 300 + 150 * __import__('math').sin(angle)})
    canvas.draw_path("du", circle, width=8, naturalize=True)
    points = canvas.state()["strokes"][0]["points"]
    assert points != [{"x": round(point["x"], 2), "y": round(point["y"], 2)} for point in circle]
    assert points[-1] != points[0]
    radii = [((point["x"] - 400) ** 2 + (point["y"] - 300) ** 2) ** .5 for point in points]
    assert max(radii) - min(radii) > 2


def test_ai_low_point_polygon_gets_curved_hand_positions(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    triangle = [{"x": 100, "y": 100}, {"x": 240, "y": 120}, {"x": 160, "y": 300}, {"x": 100, "y": 100}]
    canvas.draw_path("du", triangle, width=10, naturalize=True)
    points = canvas.state()["strokes"][0]["points"]
    assert len(points) > len(triangle)
    assert any(point["y"] != 100 + (120 - 100) * (point["x"] - 100) / 140 for point in points[1:5])


def test_ai_dense_vector_path_is_reduced_to_hand_targets(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    dense = [{"x": 200 + index * 4, "y": 250 + (index % 3)} for index in range(40)]
    canvas.draw_path("du", dense, naturalize=True)
    points = canvas.state()["strokes"][0]["points"]
    assert len(points) < len(dense)


def test_brush_medium_is_persisted(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    canvas.draw_path("lee", [{"x": 30, "y": 30}, {"x": 90, "y": 50}], brush="marker")
    assert canvas.state()["strokes"][0]["brush"] == "marker"
    assert len(canvas.png_bytes()) > 1000


def test_canvas_presence_tracks_view_color_and_drawing(tmp_path):
    canvas = SharedCanvas(tmp_path / "canvas.json")
    canvas.snapshot_payload("du")
    assert canvas.presence_for("lee")[0]["action"] == "viewing"
    canvas.select_color("du", "#33423b")
    assert canvas.presence_for("lee")[0]["action"] == "selecting"
    canvas.draw_path("du", [{"x": 20, "y": 20}])
    assert canvas.presence_for("lee")[0]["action"] == "drawing"
    canvas.presence["du"]["seen"] -= 180
    assert canvas.presence_for("lee")[0]["age"] >= 180
    canvas.presence["du"]["seen"] -= 121
    assert canvas.presence_for("lee") == []
