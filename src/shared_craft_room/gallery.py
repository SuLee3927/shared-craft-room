from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CraftGallery:
    """A small shared display shelf backed by immutable PNG snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.image_dir = path.with_suffix("")
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"items": []})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data.get("items"), list) else {"items": []}
        except (OSError, json.JSONDecodeError):
            return {"items": []}

    def _save(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    def list_items(self) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self._load()["items"]))

    def add(self, kind: str, title: str, added_by: str, authors: list[str], image: bytes, source_id: str | None = None, presentation: str | None = None, display_image: bytes | None = None, charm_size: tuple[int, int] | None = None, has_pouch: bool = False) -> dict[str, Any]:
        if kind not in {"sketch", "bead"}:
            raise ValueError("unknown gallery work type")
        title = " ".join(str(title).split())[:60] or ("共同画作" if kind == "sketch" else "拼豆成品")
        if not image:
            raise ValueError("the finished work has no image")
        with self.lock:
            data = self._load()
            item_id = uuid.uuid4().hex[:16]
            item = {
                "id": item_id, "kind": kind, "title": title, "added_by": added_by,
                "authors": list(dict.fromkeys(authors)), "source_id": source_id,
                "created_at": now(),
            }
            if presentation:
                item["presentation"] = presentation
            if kind == "bead" and display_image is not None and charm_size:
                columns, rows = charm_size
                item.update({"piece_columns": columns, "piece_rows": rows, "has_pouch": bool(has_pouch)})
            temp = self.image_dir / f".{item_id}.tmp"
            temp.write_bytes(image)
            temp.replace(self.image_dir / f"{item_id}.png")
            if display_image is not None:
                display_temp = self.image_dir / f".{item_id}-display.tmp"
                display_temp.write_bytes(display_image)
                display_temp.replace(self.image_dir / f"{item_id}-display.png")
            data["items"].append(item)
            self._save(data)
            return json.loads(json.dumps(item))

    def move(self, item_id: str, direction: str) -> list[dict[str, Any]]:
        if direction not in {"up", "down"}:
            raise ValueError("direction must be up or down")
        with self.lock:
            data = self._load()
            index = next((i for i, item in enumerate(data["items"]) if item["id"] == item_id), None)
            if index is None:
                raise ValueError("gallery work not found")
            target = index - 1 if direction == "up" else index + 1
            if 0 <= target < len(data["items"]):
                data["items"][index], data["items"][target] = data["items"][target], data["items"][index]
                self._save(data)
            return json.loads(json.dumps(data["items"]))

    def feature(self, item_id: str, slot: int | None) -> list[dict[str, Any]]:
        if slot is not None and slot not in {1, 2, 3, 4}:
            raise ValueError("display slot must be 1, 2, 3, or 4")
        with self.lock:
            data = self._load()
            item = next((entry for entry in data["items"] if entry["id"] == item_id), None)
            if item is None:
                raise ValueError("gallery work not found")
            if slot is not None and item.get("kind") == "bead" and item.get("has_pouch"):
                raise ValueError("带透明袋的拼豆请挂到袋架")
            if slot is not None:
                for entry in data["items"]:
                    if entry.get("featured_slot") == slot:
                        entry.pop("featured_slot", None)
                item["featured_slot"] = slot
                item.pop("charm_slot", None)
            else:
                item.pop("featured_slot", None)
            self._save(data)
            return json.loads(json.dumps(data["items"]))

    def hang(self, item_id: str, enabled: bool = True) -> list[dict[str, Any]]:
        with self.lock:
            data = self._load()
            item = next((entry for entry in data["items"] if entry["id"] == item_id), None)
            if item is None:
                raise ValueError("gallery work not found")
            if not enabled:
                item.pop("charm_slot", None)
                self._save(data)
                return json.loads(json.dumps(data["items"]))
            if item.get("kind") != "bead" or not item.get("has_pouch"):
                raise ValueError("只有带透明袋的拼豆成品才能挂到袋架")
            columns, rows = int(item.get("piece_columns") or 0), int(item.get("piece_rows") or 0)
            slots = {1: (12, 18), 2: (16, 16), 3: (24, 12)}
            occupied = {entry.get("charm_slot") for entry in data["items"] if entry["id"] != item_id}
            candidates = [(number, limits) for number, limits in slots.items()
                          if number not in occupied and columns <= limits[0] and rows <= limits[1]]
            if not candidates:
                raise ValueError("挂钩放不下：竖袋最多 12×18，小方袋最多 16×16，横袋最多 24×12；也可能合适的袋位已经被占用")
            slot = min(candidates, key=lambda choice: abs((columns / rows) - (choice[1][0] / choice[1][1])))[0]
            item["charm_slot"] = slot
            item.pop("featured_slot", None)
            self._save(data)
            return json.loads(json.dumps(data["items"]))

    def remove(self, item_id: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            if not any(item["id"] == item_id for item in data["items"]):
                raise ValueError("gallery work not found")
            data["items"] = [item for item in data["items"] if item["id"] != item_id]
            self._save(data)
            image = self.image_dir / f"{item_id}.png"
            if image.exists():
                image.unlink()
            display_image = self.image_dir / f"{item_id}-display.png"
            if display_image.exists():
                display_image.unlink()
            return {"removed": True, "id": item_id}

    def image_path(self, item_id: str) -> Path:
        with self.lock:
            if not any(item["id"] == item_id for item in self._load()["items"]):
                raise ValueError("gallery work not found")
            path = self.image_dir / f"{item_id}.png"
            if not path.exists():
                raise ValueError("gallery image not found")
            return path

    def display_image_path(self, item_id: str) -> Path:
        with self.lock:
            if not any(item["id"] == item_id for item in self._load()["items"]):
                raise ValueError("gallery work not found")
            path = self.image_dir / f"{item_id}-display.png"
            if not path.exists():
                raise ValueError("gallery display image not found")
            return path
