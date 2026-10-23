from __future__ import annotations

import io
import base64
import json
import math
import threading
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


MARD_COLORS = [
    {"code": "H18", "name": "奶油白", "hex": "#fffdf0"},
    {"code": "F14", "name": "浅粉红", "hex": "#ffa9ad"},
    {"code": "E4", "name": "玫瑰粉", "hex": "#e8649e"},
    {"code": "F19", "name": "砖红", "hex": "#c1444a"},
    {"code": "F7", "name": "深红", "hex": "#971937"},
    {"code": "A14", "name": "亮红", "hex": "#f75842"},
    {"code": "A6", "name": "亮橙", "hex": "#fda951"},
    {"code": "A5", "name": "黄色", "hex": "#f0d83a"},
    {"code": "B13", "name": "浅草绿", "hex": "#c8e87d"},
    {"code": "B17", "name": "草绿色", "hex": "#9eb33e"},
    {"code": "B25", "name": "青绿色", "hex": "#4e846d"},
    {"code": "C22", "name": "灰青色", "hex": "#6bb1bb"},
    {"code": "C6", "name": "天蓝色", "hex": "#54a7e9"},
    {"code": "D2", "name": "淡紫色", "hex": "#868dd3"},
    {"code": "G17", "name": "深咖色", "hex": "#56403c"},
    {"code": "H7", "name": "黑色", "hex": "#000000"},
    {"code": "H2", "name": "白色", "hex": "#ffffff"},
    {"code": "H11", "name": "浅灰紫", "hex": "#cecdd5"},
]
PALETTE = [item["hex"] for item in MARD_COLORS]
MARD_BY_HEX = {item["hex"]: item for item in MARD_COLORS}
MARD_BY_TOKEN = {
    str(token).strip().lower(): item["hex"]
    for item in MARD_COLORS
    for token in (item["hex"], item["code"], item["name"])
}

# Boards made before the MARD-labelled palette keep their work, but are
# normalised to the closest colour in the new compact MARD selection.
LEGACY_COLORS = dict(zip([
    "#f7eee2", "#f4c7cf", "#dc7892", "#b74766", "#8e2949", "#ed7359",
    "#f4aa43", "#f4d35e", "#b9d66b", "#6cad67", "#4e8d80", "#78c8cf",
    "#6594c7", "#7867a7", "#704b3b", "#25282d", "#ffffff", "#b8b8b8",
], PALETTE))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unix_now() -> float:
    return datetime.now(timezone.utc).timestamp()


class BeadBoards:
    SIZES = {8, 12, 16, 24, 32, 48, 64}
    MODES = {"together", "separate", "gift"}
    PRESENCE_TTL = 300

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.presence: dict[tuple[str, str], dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"revision": 0, "boards": []})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for board in data.get("boards", []):
                board.setdefault("craft", {"stage": "beading"})
                board.setdefault("activity", None)
                board.setdefault("selections", {})
                board.setdefault("work_sessions", {})
                for bead in board.get("cells", {}).values():
                    bead["color"] = LEGACY_COLORS.get(bead.get("color"), bead.get("color"))
                inventories = board.get("inventories", {})
                for actor, inventory in inventories.items():
                    normalised: dict[str, int] = {}
                    for color, count in inventory.items():
                        key = LEGACY_COLORS.get(color, color)
                        normalised[key] = normalised.get(key, 0) + int(count)
                    inventories[actor] = normalised
            return data
        except (OSError, json.JSONDecodeError):
            return {"revision": 0, "boards": []}

    def _save(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    def save_decoration(self, actor: str, board_id: str, data_url: str, piece_data_url: str = "", has_pouch: bool = False) -> dict[str, Any]:
        def decode_png(value: str, label: str) -> bytes:
            if not value.startswith("data:image/png;base64,"):
                raise ValueError(f"{label} must be a PNG image")
            try:
                raw_image = base64.b64decode(value.split(",", 1)[1], validate=True)
            except Exception as exc:
                raise ValueError(f"{label} is invalid") from exc
            if not 50 <= len(raw_image) <= 6_000_000:
                raise ValueError(f"{label} is too large")
            return raw_image

        raw = decode_png(data_url, "decorated work")
        piece_raw = decode_png(piece_data_url, "display piece") if piece_data_url else None
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            craft = board.setdefault("craft", {"stage": "beading"})
            if craft.get("stage") != "finished":
                raise ValueError("finish ironing before decorating")
            folder = self.path.with_name("shared-bead-finished")
            folder.mkdir(parents=True, exist_ok=True)
            temp = folder / f".{board_id}.tmp"
            temp.write_bytes(raw)
            temp.replace(folder / f"{board_id}.png")
            if piece_raw is not None:
                piece_temp = folder / f".{board_id}-piece.tmp"
                piece_temp.write_bytes(piece_raw)
                piece_temp.replace(folder / f"{board_id}-piece.png")
            craft["decorated"] = True
            craft["has_pouch"] = bool(has_pouch)
            craft["decorated_at"] = now()
            board["revision"] += 1
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            return {"saved": True, "decorated": True, "has_pouch": craft["has_pouch"], "revision": board["revision"]}

    def decorated_bytes(self, actor: str, board_id: str) -> bytes:
        board = self.get(actor, board_id)
        if not board.get("craft", {}).get("decorated"):
            raise ValueError("save the decorated finished work first")
        path = self.path.with_name("shared-bead-finished") / f"{board_id}.png"
        if not path.exists():
            raise ValueError("decorated finished work image is missing")
        return path.read_bytes()

    def display_piece_bytes(self, actor: str, board_id: str) -> bytes:
        board = self.get(actor, board_id)
        if not board.get("craft", {}).get("decorated"):
            raise ValueError("save the decorated finished work first")
        path = self.path.with_name("shared-bead-finished") / f"{board_id}-piece.png"
        if not path.exists():
            raise ValueError("save this finished work again before displaying it")
        return path.read_bytes()

    @staticmethod
    def _visible(board: dict[str, Any], actor: str) -> bool:
        return board["mode"] != "gift" or board["owner"] == actor or board.get("revealed", False)

    def list_boards(self, actor: str) -> list[dict[str, Any]]:
        with self.lock:
            result = []
            for board in self._load()["boards"]:
                if not self._visible(board, actor):
                    continue
                item = {k: v for k, v in board.items() if k not in {"cells", "inventories", "reference_image"}}
                item["bead_count"] = len(board.get("cells", {}))
                item["has_reference"] = bool(board.get("reference_image"))
                result.append(item)
            return result

    def create(self, actor: str, title: str, mode: str, size: int) -> dict[str, Any]:
        title = " ".join(str(title).split())[:40] or "没有名字的小豆板"
        size = int(size)
        if mode not in self.MODES:
            raise ValueError("mode must be together, separate, or gift")
        if size not in self.SIZES:
            raise ValueError("size must be 8, 12, 16, 24, 32, 48, or 64")
        with self.lock:
            data = self._load()
            board = {
                "id": uuid.uuid4().hex[:12], "title": title, "mode": mode, "size": size,
                "owner": actor, "revealed": mode != "gift", "cells": {}, "inventories": {},
                "reference_image": None, "craft": {"stage": "beading"},
                "revision": 0, "created_at": now(), "updated_at": now(),
            }
            data["boards"].append(board)
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            return self.get(actor, board["id"])

    def delete(self, actor: str, board_id: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if board["owner"] != actor:
                raise ValueError("only the person who took this board can remove it from the shelf")
            data["boards"] = [item for item in data["boards"] if item["id"] != board_id]
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            return {"deleted": True, "id": board_id}

    def _find(self, data: dict[str, Any], board_id: str) -> dict[str, Any]:
        board = next((b for b in data["boards"] if b["id"] == board_id), None)
        if board is None:
            raise ValueError("bead board not found")
        return board

    def get(self, actor: str, board_id: str) -> dict[str, Any]:
        with self.lock:
            board = self._find(self._load(), board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            result = json.loads(json.dumps(board))
            sessions = result.pop("work_sessions", {})
            result["work_session"] = sessions.get(actor)
            craft = result.setdefault("craft", {"stage": "beading"})
            clock = unix_now()
            craft["heat_remaining"] = max(0.0, float(craft.get("heat_ready_at", 0)) - clock)
            craft["cool_remaining"] = max(0.0, float(craft.get("cool_ready_at", 0)) - clock)
            result["palette"] = MARD_COLORS
            for bead in result.get("cells", {}).values():
                bead["code"] = MARD_BY_HEX.get(bead.get("color"), {}).get("code")
            self.touch(actor, board_id, "viewing")
            return result

    def touch(self, actor: str, board_id: str, action: str = "viewing", color: str | None = None) -> None:
        with self.lock:
            previous = self.presence.get((board_id, actor))
            if action == "viewing" and previous and previous.get("action") != "viewing" and time.monotonic() - previous["seen"] < 20:
                return
            self.presence[(board_id, actor)] = {"action": action, "color": color, "seen": time.monotonic()}

    def presence_for(self, actor: str, board_id: str) -> list[dict[str, Any]]:
        clock = time.monotonic()
        with self.lock:
            return [{"actor": participant, "action": details["action"], "color": details.get("color"), "age": round(clock - details["seen"], 1)} for (item_id, participant), details in self.presence.items() if item_id == board_id and participant != actor and clock - details["seen"] < self.PRESENCE_TTL]

    def _inventory(self, board: dict[str, Any], actor: str) -> dict[str, int]:
        inventory = board.setdefault("inventories", {}).setdefault(actor, {})
        for color in PALETTE:
            inventory.setdefault(color, 80)
        return inventory

    @staticmethod
    def _record_activity(board: dict[str, Any], actor: str, action: str, **details: Any) -> None:
        board["activity"] = {"actor": actor, "action": action, "at": now(), **details}

    @staticmethod
    def _color(value: Any) -> str:
        token = str(value).strip().lower()
        token = LEGACY_COLORS.get(token, token)
        color = MARD_BY_TOKEN.get(token)
        if color is None:
            raise ValueError("choose a palette color by MARD code, Chinese name, or hex value")
        return color

    def select_color(self, actor: str, board_id: str, color: str) -> dict[str, Any]:
        color = self._color(color)
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            board.setdefault("selections", {})[actor] = color
            self._record_activity(board, actor, "select", color=color)
            board["revision"] += 1
            board["updated_at"] = now()
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            self.touch(actor, board_id, "selecting", color)
            return {"selected": color, "revision": board["revision"]}

    def set_work_plan(self, actor: str, board_id: str, beads: list[dict[str, Any]], title: str = "") -> dict[str, Any]:
        if not 1 <= len(beads) <= 512:
            raise ValueError("a work plan needs 1 to 512 bead steps")
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            clean = []
            seen = set()
            for bead in beads:
                x, y = int(bead["x"]), int(bead["y"])
                if not 0 <= x < board["size"] or not 0 <= y < board["size"]:
                    raise ValueError("bead coordinates are outside the board")
                key = f"{x},{y}"
                if key in seen:
                    raise ValueError(f"work plan repeats peg {key}")
                seen.add(key)
                clean.append({"x": x, "y": y, "color": self._color(bead["color"])})
            session = {"title": " ".join(str(title).split())[:60] or "未完成的拼豆", "remaining": clean, "total": len(clean), "updated_at": now()}
            board.setdefault("work_sessions", {})[actor] = session
            board["reference_image"] = self._pattern_reference(board["size"], clean)
            board["revision"] += 1
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            return {"work_session": session, "revision": board["revision"], "reference_pinned": True}

    @staticmethod
    def _pattern_reference(size: int, beads: list[dict[str, Any]]) -> str:
        side, margin = 640, 32
        cell = (side - margin * 2) / size
        image = Image.new("RGBA", (side, side), "#fffaf0")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, side - 8, side - 8), radius=24, outline="#d8c4ab", width=4)
        for bead in beads:
            cx, cy = margin + (bead["x"] + .5) * cell, margin + (bead["y"] + .5) * cell
            radius = max(2.0, cell * .42)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=bead["color"], outline="#ffffff", width=max(1, round(cell * .06)))
        output = io.BytesIO()
        image.save(output, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    def place(self, actor: str, board_id: str, beads: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(beads) <= 5:
            raise ValueError("place 1 to 5 beads at a time; this board is meant to be made by hand")
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            if board.setdefault("craft", {"stage": "beading"})["stage"] != "beading":
                raise ValueError("the ironing paper is already on; finish this piece before moving beads")
            inventory = self._inventory(board, actor)
            clean = []
            for bead in beads:
                x, y, color = int(bead["x"]), int(bead["y"]), self._color(bead["color"])
                if not 0 <= x < board["size"] or not 0 <= y < board["size"]:
                    raise ValueError("bead coordinates are outside the board")
                key = f"{x},{y}"
                if key in board["cells"]:
                    raise ValueError(f"peg {key} is occupied; take that bead first")
                if inventory[color] <= 0:
                    raise ValueError(f"no {color} beads left")
                clean.append((key, color, x, y))
            for key, color, x, y in clean:
                inventory[color] -= 1
                board["cells"][key] = {"x": x, "y": y, "color": color, "actor": actor}
            board.setdefault("selections", {})[actor] = clean[-1][1]
            session = board.setdefault("work_sessions", {}).get(actor)
            if session:
                placed = {(x, y, color) for _, color, x, y in clean}
                session["remaining"] = [step for step in session.get("remaining", []) if (step["x"], step["y"], step["color"]) not in placed]
                session["updated_at"] = now()
                if not session["remaining"]:
                    board["work_sessions"].pop(actor, None)
            colors = list(dict.fromkeys(color for _, color, _, _ in clean))
            self._record_activity(board, actor, "place", count=len(clean), color=clean[-1][1], colors=colors)
            board["revision"] += 1
            board["updated_at"] = now()
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            self.touch(actor, board_id, "placing", clean[-1][1])
            return {"placed": len(clean), "revision": board["revision"], "bead_count": len(board["cells"]), "work_remaining": len(session.get("remaining", [])) if session else None}

    def take(self, actor: str, board_id: str, x: int, y: int) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            if board.setdefault("craft", {"stage": "beading"})["stage"] != "beading":
                raise ValueError("the ironing paper is already on; finish this piece before moving beads")
            key = f"{int(x)},{int(y)}"
            bead = board["cells"].get(key)
            if bead is None:
                raise ValueError("there is no bead on that peg")
            if board["mode"] == "separate" and bead["actor"] != actor:
                raise ValueError("on separate boards you may only take your own beads")
            del board["cells"][key]
            self._inventory(board, bead["actor"])[bead["color"]] += 1
            self._record_activity(board, actor, "take", color=bead["color"])
            board["revision"] += 1
            board["updated_at"] = now()
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            self.touch(actor, board_id, "taking", bead["color"])
            return {"taken": True, "color": bead["color"], "revision": board["revision"], "bead_count": len(board["cells"])}

    def refill(self, actor: str, board_id: str, color: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            if board.setdefault("craft", {"stage": "beading"})["stage"] != "beading":
                raise ValueError("this piece is already being finished")
            color = self._color(color)
            inventory = self._inventory(board, actor)
            if inventory[color] > 0:
                raise ValueError("finish the open bag before opening another one")
            inventory[color] += 80
            self._record_activity(board, actor, "refill", color=color)
            board["revision"] += 1
            board["updated_at"] = now()
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            self.touch(actor, board_id, "refilling", color)
            return {"refilled": 80, "color": color, "count": inventory[color], "revision": board["revision"]}

    def craft(self, actor: str, board_id: str, action: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if not self._visible(board, actor):
                raise ValueError("this surprise board is still hidden")
            craft = board.setdefault("craft", {"stage": "beading"})
            stage, clock = craft.get("stage", "beading"), unix_now()
            if action == "cover":
                if stage != "beading":
                    raise ValueError("the piece is not ready to cover")
                if not board.get("cells"):
                    raise ValueError("place at least one bead before covering the board")
                craft.update({"stage": "covered", "covered_by": actor, "covered_at": clock})
            elif action == "uncover":
                if stage not in {"covered", "heating"}:
                    raise ValueError("the paper can no longer be lifted")
                craft = {"stage": "beading"}
                board["craft"] = craft
            elif action == "heat":
                if stage != "covered":
                    raise ValueError("cover the beads before heating the iron")
                wait = random.uniform(3.2, 4.8)
                craft.update({"stage": "heating", "heated_by": actor, "heat_started_at": clock, "heat_ready_at": clock + wait})
            elif action == "start_iron":
                if stage != "heating" or clock < float(craft.get("heat_ready_at", 0)):
                    raise ValueError("the iron is not hot enough yet")
                craft.update({"stage": "ironing", "ironed_by": actor, "iron_started_at": clock})
            elif action == "finish_iron":
                if stage != "ironing":
                    raise ValueError("the iron is not pressing the piece")
                actual_seconds = max(0.0, clock - float(craft.get("iron_started_at", clock)))
                effective_seconds = min(12.0, actual_seconds)
                quality = "under" if effective_seconds < 2.8 else "good" if effective_seconds <= 6.2 else "over"
                craft.update({"stage": "cooling", "iron_seconds": round(effective_seconds, 2),
                              "actual_iron_seconds": round(actual_seconds, 2), "quality": quality,
                              "cool_ready_at": clock + 3.0})
            elif action == "lift":
                if stage != "cooling" or clock < float(craft.get("cool_ready_at", 0)):
                    raise ValueError("let the piece cool before lifting it")
                craft.update({"stage": "finished", "lifted_by": actor, "finished_at": clock})
            else:
                raise ValueError("unknown craft action")
            self._record_activity(board, actor, "craft", craft_action=action)
            board["revision"] += 1
            board["updated_at"] = now()
            data["revision"] = int(data.get("revision", 0)) + 1
            self._save(data)
            return {"action": action, "stage": craft["stage"], "revision": board["revision"],
                    "craft": self.get(actor, board_id)["craft"]}

    def reveal(self, actor: str, board_id: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if board["owner"] != actor:
                raise ValueError("only the maker can reveal this gift")
            board["revealed"] = True
            board["revision"] += 1
            board["updated_at"] = now()
            self._save(data)
            return {"revealed": True, "board_id": board_id, "revision": board["revision"]}

    def set_reference(self, actor: str, board_id: str, data_url: str | None) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            board = self._find(data, board_id)
            if board["owner"] != actor:
                raise ValueError("only the board maker can change the reference note")
            if data_url and (not data_url.startswith("data:image/") or len(data_url) > 1_500_000):
                raise ValueError("reference image must be an image under 1 MB")
            board["reference_image"] = data_url
            board["revision"] += 1
            board["updated_at"] = now()
            self._save(data)
            return {"saved": True, "has_reference": bool(data_url)}

    def png_bytes(self, actor: str, board_id: str) -> bytes:
        board = self.get(actor, board_id)
        size, margin, cell = board["size"], 70, 28
        side = margin * 2 + size * cell
        image = Image.new("RGBA", (side, side), "#f8f1e8")
        draw = ImageDraw.Draw(image)
        finished = board.get("craft", {}).get("stage") == "finished"
        draw.rounded_rectangle((25, 25, side - 25, side - 25), radius=34,
                               fill="#f8f1e8" if finished else "#eee3d4", outline="#cabaa6", width=4)
        if not finished:
            for y in range(size):
                for x in range(size):
                    cx, cy = margin + x * cell + cell / 2, margin + y * cell + cell / 2
                    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill="#c7b9a8")
        if finished:
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            fused = ImageDraw.Draw(layer)
            bridge, tile, radius = cell * .92, cell * 1.015, max(2, round(cell * .075))
            cells = board["cells"]
            for key, bead in cells.items():
                gx, gy = (int(part) for part in key.split(","))
                cx, cy = margin + gx * cell + cell / 2, margin + gy * cell + cell / 2
                for dx, dy in ((1, 0), (0, 1)):
                    other = cells.get(f"{gx + dx},{gy + dy}")
                    if other is None:
                        continue
                    nx, ny = cx + dx * cell, cy + dy * cell
                    if dx:
                        fused.rectangle((cx, cy-bridge/2, (cx+nx)/2, cy+bridge/2), fill=bead["color"])
                        fused.rectangle(((cx+nx)/2, cy-bridge/2, nx, cy+bridge/2), fill=other["color"])
                    else:
                        fused.rectangle((cx-bridge/2, cy, cx+bridge/2, (cy+ny)/2), fill=bead["color"])
                        fused.rectangle((cx-bridge/2, (cy+ny)/2, cx+bridge/2, ny), fill=other["color"])
                right = cells.get(f"{gx + 1},{gy}")
                down = cells.get(f"{gx},{gy + 1}")
                diagonal = cells.get(f"{gx + 1},{gy + 1}")
                if right and down and diagonal:
                    mx, my, half = cx + cell / 2, cy + cell / 2, bridge / 2
                    fused.rectangle((mx-half, my-half, mx, my), fill=bead["color"])
                    fused.rectangle((mx, my-half, mx+half, my), fill=right["color"])
                    fused.rectangle((mx-half, my, mx, my+half), fill=down["color"])
                    fused.rectangle((mx, my, mx+half, my+half), fill=diagonal["color"])
            for bead in cells.values():
                cx = margin + bead["x"] * cell + cell / 2
                cy = margin + bead["y"] * cell + cell / 2
                fused.rounded_rectangle((cx-tile/2, cy-tile/2, cx+tile/2, cy+tile/2), radius=radius,
                                        fill=bead["color"])
            texture_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            texture = ImageDraw.Draw(texture_layer)
            rng = random.Random(f"{board_id}:{board.get('revision', 0)}")
            for bead in cells.values():
                cx = margin + bead["x"] * cell + cell / 2
                cy = margin + bead["y"] * cell + cell / 2
                texture.rounded_rectangle((cx-tile/2, cy-tile/2, cx+tile/2, cy+tile/2), radius=radius,
                                          outline=(52, 32, 28, 46), width=1)
                texture.arc((cx-cell*.34, cy-cell*.34, cx+cell*.34, cy+cell*.34), 205, 335,
                            fill=(255, 255, 255, 54), width=1)
                hole = cell * (.026 + rng.random() * .008)
                texture.ellipse((cx-hole*1.28+1, cy-hole*1.28+1, cx+hole*1.28+1, cy+hole*1.28+1),
                                fill=(53, 35, 30, 55))
                texture.ellipse((cx-hole, cy-hole, cx+hole, cy+hole), fill=(248, 241, 232, 205),
                                outline=(255, 255, 255, 95), width=1)
                for index in range(5):
                    angle, radial = rng.uniform(0, math.tau), rng.uniform(0, cell*.34)
                    length = rng.uniform(cell*.035, cell*.14)
                    px, py = cx + math.cos(angle)*radial, cy + math.sin(angle)*radial
                    turn = angle + rng.uniform(-.9, .9)
                    tone = (255, 255, 255, 27) if index % 3 else (45, 28, 24, 19)
                    texture.line((px, py, px+math.cos(turn)*length, py+math.sin(turn)*length), fill=tone, width=1)
            layer.alpha_composite(texture_layer)
            shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
            shadow.alpha_composite(layer, (0, max(1, round(cell*.1))))
            shadow.putalpha(shadow.getchannel("A").point(lambda alpha: round(alpha*.18)))
            image.alpha_composite(shadow)
            image.alpha_composite(layer)
        for bead in board["cells"].values():
            if finished:
                continue
            cx, cy = margin + bead["x"] * cell + cell / 2, margin + bead["y"] * cell + cell / 2
            r = cell * .43
            draw.ellipse((cx-r+2, cy-r+3, cx+r+2, cy+r+3), fill="#aa9f93")
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=bead["color"], outline="#ffffff", width=1)
            hole = 3.5
            draw.ellipse((cx-hole, cy-hole, cx+hole, cy+hole), fill="#f8f1e8")
            draw.ellipse((cx-r*.55, cy-r*.62, cx-r*.18, cy-r*.25), fill="#ffffff")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()
