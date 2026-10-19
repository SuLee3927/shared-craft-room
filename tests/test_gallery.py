from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.gallery import CraftGallery


def test_gallery_add_move_remove_and_snapshot(tmp_path: Path):
    gallery = CraftGallery(tmp_path / "gallery.json")
    first = gallery.add("sketch", " 一起 画画 ", "human", ["Alice", "CraftBot"], b"first")
    second = gallery.add("bead", "小猫", "assistant", ["CraftBot"], b"second", "board-1")

    assert [item["id"] for item in gallery.list_items()] == [first["id"], second["id"]]
    assert gallery.image_path(first["id"]).read_bytes() == b"first"
    assert first["title"] == "一起 画画"

    gallery.move(second["id"], "up")
    assert [item["id"] for item in gallery.list_items()] == [second["id"], first["id"]]

    gallery.feature(first["id"], 2)
    assert gallery.list_items()[1]["featured_slot"] == 2
    gallery.feature(second["id"], 2)
    featured = gallery.list_items()
    assert featured[0]["featured_slot"] == 2
    assert "featured_slot" not in featured[1]

    gallery.remove(second["id"])
    assert [item["id"] for item in gallery.list_items()] == [first["id"]]
    assert not (gallery.image_dir / f"{second['id']}.png").exists()


def test_gallery_rejects_unknown_kind(tmp_path: Path):
    gallery = CraftGallery(tmp_path / "gallery.json")
    try:
        gallery.add("video", "x", "lee", [], b"x")
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("unknown gallery kind was accepted")


def test_gallery_assigns_generated_pouch_slots_and_removes_display_image(tmp_path: Path):
    gallery = CraftGallery(tmp_path / "gallery.json")
    square = gallery.add("bead", "方形", "human", ["Alice"], b"full", "board-1", "decorated", b"piece", (12, 12), True)
    portrait = gallery.add("bead", "竖形", "human", ["Alice"], b"full", "board-2", "decorated", b"piece", (8, 17), True)
    landscape = gallery.add("bead", "横形", "human", ["Alice"], b"full", "board-3", "decorated", b"piece", (22, 10), True)

    assert not any("charm_slot" in item for item in (square, portrait, landscape))
    assert next(item for item in gallery.hang(square["id"]) if item["id"] == square["id"])["charm_slot"] == 2
    assert next(item for item in gallery.hang(portrait["id"]) if item["id"] == portrait["id"])["charm_slot"] == 1
    assert next(item for item in gallery.hang(landscape["id"]) if item["id"] == landscape["id"])["charm_slot"] == 3
    assert gallery.display_image_path(square["id"]).read_bytes() == b"piece"

    gallery.remove(square["id"])
    assert not (gallery.image_dir / f"{square['id']}-display.png").exists()


def test_gallery_rejects_piece_that_does_not_fit_generated_pouches(tmp_path: Path):
    gallery = CraftGallery(tmp_path / "gallery.json")
    try:
        item = gallery.add("bead", "太大", "human", ["Alice"], b"full", "board-1", "decorated", b"piece", (25, 19), True)
        gallery.hang(item["id"])
    except ValueError as exc:
        assert "12×18" in str(exc)
    else:
        raise AssertionError("oversized bead piece was accepted")
