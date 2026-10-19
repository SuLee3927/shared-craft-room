from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw


class SharedCanvas:
    WIDTH = 1200
    HEIGHT = 800
    SIZES = {(1200, 800), (800, 1200)}
    PRESENCE_TTL = 300

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.presence: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"revision": 0, "background": "#fffdf7", "strokes": [], "width": self.WIDTH, "height": self.HEIGHT})

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"revision": 0, "background": "#fffdf7", "strokes": []}

    def _save(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    def state(self) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            width, height = self._dimensions(data)
            return {**data, "width": width, "height": height}

    def touch(self, actor: str, action: str = "viewing", color: str | None = None) -> None:
        with self.lock:
            self.presence[actor] = {"action": action, "color": color, "seen": time.monotonic()}

    def presence_for(self, actor: str) -> list[dict[str, Any]]:
        clock = time.monotonic()
        with self.lock:
            return [{"actor": participant, "action": details["action"], "color": details.get("color"), "age": round(clock - details["seen"], 1)} for participant, details in self.presence.items() if participant != actor and clock - details["seen"] < self.PRESENCE_TTL]

    def select_color(self, actor: str, color: str) -> dict[str, Any]:
        if not self._valid_color(color):
            raise ValueError("color must be a hex color")
        self.touch(actor, "selecting", color.lower())
        return {"selected": color.lower()}

    def clear(self, actor: str, background: str = "#fffdf7", width: int | None = None, height: int | None = None) -> dict[str, Any]:
        if not self._valid_color(background):
            raise ValueError("background must be a hex color")
        with self.lock:
            old = self._load()
            old_width, old_height = self._dimensions(old)
            width, height = int(width or old_width), int(height or old_height)
            if (width, height) not in self.SIZES:
                raise ValueError("canvas must be 1200 x 800 or 800 x 1200")
            data = {"revision": int(old.get("revision", 0)) + 1, "background": background, "strokes": [], "last_actor": actor, "width": width, "height": height}
            self._save(data)
            return self.state()

    def resize(self, actor: str, width: int, height: int) -> dict[str, Any]:
        """Resize an existing canvas while preserving its visible composition."""
        if (int(width), int(height)) not in self.SIZES:
            raise ValueError("canvas must be 1200 x 800 or 800 x 1200")
        with self.lock:
            data = self._load()
            old_width, old_height = self._dimensions(data)
            width, height = int(width), int(height)
            if (old_width, old_height) == (width, height):
                return self.state()
            scale_x, scale_y = width / old_width, height / old_height
            for stroke in data.get("strokes", []):
                stroke["points"] = [{"x": round(float(point["x"]) * scale_x, 2), "y": round(float(point["y"]) * scale_y, 2)} for point in stroke.get("points", [])]
            data.update({"width": width, "height": height, "revision": int(data.get("revision", 0)) + 1, "last_actor": actor})
            self._save(data)
            return self.state()

    def draw_path(self, actor: str, points: list[dict[str, Any]], color: str = "#33423b", width: float = 8, opacity: float = 1, mode: str = "draw", brush: str = "pen", naturalize: bool = False) -> dict[str, Any]:
        if not 1 <= len(points) <= 500:
            raise ValueError("points must contain 1 to 500 points")
        if not self._valid_color(color):
            raise ValueError("color must be a hex color")
        if not 1 <= float(width) <= 100:
            raise ValueError("width must be between 1 and 100")
        if not 0.05 <= float(opacity) <= 1:
            raise ValueError("opacity must be between 0.05 and 1")
        if mode not in {"draw", "erase", "fill"}:
            raise ValueError("mode must be draw, erase, or fill")
        if brush not in {"pencil", "pen", "marker", "brush"}:
            raise ValueError("brush must be pencil, pen, marker, or brush")
        with self.lock:
            data = self._load()
            canvas_width, canvas_height = self._dimensions(data)
            clean = []
            for point in points:
                x, y = float(point["x"]), float(point["y"])
                if not 0 <= x <= canvas_width or not 0 <= y <= canvas_height:
                    raise ValueError(f"point is outside the {canvas_width} x {canvas_height} canvas")
                clean.append({"x": round(x, 2), "y": round(y, 2)})
            if mode == "fill" and len(clean) != 1:
                raise ValueError("fill needs exactly one starting point")
            if naturalize and mode == "draw":
                clean = self._naturalize(clean, actor, color, float(width), canvas_width, canvas_height)
            stroke = {"id": uuid.uuid4().hex, "actor": actor, "points": clean, "color": color.lower(), "width": float(width), "opacity": float(opacity), "mode": mode, "brush": brush}
            data.setdefault("strokes", []).append(stroke)
            data["revision"] = int(data.get("revision", 0)) + 1
            data["last_actor"] = actor
            self._save(data)
            self.touch(actor, "drawing")
            return {"saved": True, "stroke_id": stroke["id"], "revision": data["revision"], "stroke_count": len(data["strokes"])}

    def undo(self, actor: str) -> dict[str, Any]:
        with self.lock:
            data = self._load()
            strokes = data.setdefault("strokes", [])
            index = next((i for i in range(len(strokes) - 1, -1, -1) if strokes[i].get("actor") == actor), None)
            if index is None:
                return {"undone": False, "reason": "no stroke by this participant"}
            removed = strokes.pop(index)
            data["revision"] = int(data.get("revision", 0)) + 1
            data["last_actor"] = actor
            self._save(data)
            return {"undone": True, "stroke_id": removed.get("id"), "revision": data["revision"]}

    def png_bytes(self) -> bytes:
        data = self.state()
        image = Image.new("RGBA", (data["width"], data["height"]), data.get("background", "#fffdf7"))
        for stroke in data.get("strokes", []):
            points = [(p["x"], p["y"]) for p in stroke.get("points", [])]
            if not points:
                continue
            if stroke.get("mode") == "fill":
                x, y = points[0]
                ImageDraw.floodfill(image, (round(x), round(y)), (*ImageColor.getrgb(stroke.get("color", "#33423b")), 255), thresh=24)
                continue
            if stroke.get("mode") == "erase":
                fill = data.get("background", "#fffdf7")
            else:
                rgb = Image.new("RGBA", (1, 1), stroke.get("color", "#33423b"))
                r, g, b, _ = rgb.getpixel((0, 0))
                fill = (r, g, b, round(255 * float(stroke.get("opacity", 1))))
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            painter = ImageDraw.Draw(layer)
            brush = stroke.get("brush", "pen")
            width = round(float(stroke.get("width", 8)) * {"pencil": .65, "pen": 1, "marker": 1.8, "brush": 1.35}.get(brush, 1))
            if brush == "pencil" and isinstance(fill, tuple):
                fill = (*fill[:3], round(fill[3] * .7))
            elif brush == "marker" and isinstance(fill, tuple):
                fill = (*fill[:3], round(fill[3] * .42))
            if len(set(points)) == 1:
                x, y = points[0]
                painter.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=fill)
            else:
                painter.line(points, fill=fill, width=width, joint="curve")
            image = Image.alpha_composite(image, layer)
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _naturalize(points: list[dict[str, float]], actor: str, color: str, width: float, canvas_width: int, canvas_height: int) -> list[dict[str, float]]:
        """Treat AI coordinates as an intended guide, then simulate one human hand motion."""
        if len(points) > 14:
            last = len(points) - 1
            points = [points[round(index * last / 13)] for index in range(14)]
        if len(points) == 1:
            return points
        if len(points) == 2:
            a, b = points
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            length = math.hypot(dx, dy)
            if length < 10:
                return points
            nx, ny = -dy / length, dx / length
            seed = hashlib.sha256(f"{actor}:{color}:{a}:{b}:{uuid.uuid4().hex}".encode()).digest()[0]
            bend = ((seed / 255) - .5) * min(9, max(2.2, width * .45, length / 150))
            return [a, {"x": round((a["x"] + b["x"]) / 2 + nx * bend, 2), "y": round((a["y"] + b["y"]) / 2 + ny * bend, 2)}, b]

        original = points
        closed = math.hypot(original[-1]["x"] - original[0]["x"], original[-1]["y"] - original[0]["y"]) <= max(12, width * 2)
        # AI often describes an organic outline with only its geometric corners.
        # Add intermediate hand positions so long polygon edges can actually bow
        # and wander instead of remaining ruler-straight between jittered vertices.
        points = [original[0]]
        for before, after in zip(original, original[1:]):
            distance = math.hypot(after["x"] - before["x"], after["y"] - before["y"])
            divisions = max(1, math.ceil(distance / 22))
            for step in range(1, divisions + 1):
                ratio = step / divisions
                points.append({
                    "x": before["x"] + (after["x"] - before["x"]) * ratio,
                    "y": before["y"] + (after["y"] - before["y"]) * ratio,
                })
        lengths = [0.0]
        for previous, point in zip(points, points[1:]):
            lengths.append(lengths[-1] + math.hypot(point["x"] - previous["x"], point["y"] - previous["y"]))
        total = lengths[-1]
        if total < 10:
            return points
        amount = min(16, max(2.0, width * (.9 if closed else .3), total / (65 if closed else 145)))
        seed = hashlib.sha256(f"{actor}:{color}:{points[0]}:{len(points)}:{uuid.uuid4().hex}".encode()).digest()
        phase_a = seed[0] / 255 * math.tau
        phase_b = seed[1] / 255 * math.tau
        handedness = -1 if seed[2] % 2 else 1
        result = []
        for index, point in enumerate(points):
            before = points[max(0, index - 1)]
            after = points[min(len(points) - 1, index + 1)]
            dx, dy = after["x"] - before["x"], after["y"] - before["y"]
            span = max(.001, math.hypot(dx, dy))
            nx, ny = -dy / span, dx / span
            progress = lengths[index] / total
            wobble = (math.sin(progress * math.tau * 1.65 + phase_a) * .68 +
                      math.sin(progress * math.tau * 4.4 + phase_b) * .32) * amount
            drift = math.sin(progress * math.pi) * amount * .28 * handedness
            if index == 0:
                wobble *= .12
                drift = 0
            elif index == len(points) - 1:
                if closed:
                    wobble += amount * (.65 if seed[3] % 2 else -.65)
                    drift += amount * .28
                else:
                    wobble *= .18
                    drift = 0
            x = min(canvas_width, max(0, point["x"] + nx * wobble + dx / span * drift))
            y = min(canvas_height, max(0, point["y"] + ny * wobble + dy / span * drift))
            result.append({"x": round(x, 2), "y": round(y, 2)})
        return result

    def snapshot_payload(self, actor: str | None = None) -> dict[str, Any]:
        if actor:
            self.touch(actor, "viewing")
        state = self.state()
        return {"revision": state["revision"], "stroke_count": len(state.get("strokes", [])), "width": state["width"], "height": state["height"], "_image_base64": base64.b64encode(self.png_bytes()).decode("ascii")}

    @classmethod
    def _dimensions(cls, data: dict[str, Any]) -> tuple[int, int]:
        dimensions = (int(data.get("width") or cls.WIDTH), int(data.get("height") or cls.HEIGHT))
        return dimensions if dimensions in cls.SIZES else (cls.WIDTH, cls.HEIGHT)

    @staticmethod
    def _valid_color(value: str) -> bool:
        return isinstance(value, str) and len(value) in {4, 7} and value.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in value[1:])
