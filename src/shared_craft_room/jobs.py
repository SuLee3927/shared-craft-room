from __future__ import annotations

import threading
import time
import uuid
from typing import Any


class CraftJobs:
    """Runs visible craft actions gradually after one short MCP call."""

    def __init__(self, canvas: Any, beads: Any) -> None:
        self.canvas = canvas
        self.beads = beads
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active: dict[tuple[str, str], str] = {}

    def _start(self, actor: str, kind: str, total: int, worker: Any) -> dict[str, Any]:
        key = (actor, kind)
        with self.lock:
            active_id = self.active.get(key)
            if active_id and self.jobs.get(active_id, {}).get("status") in {"queued", "running"}:
                raise ValueError(f"a {kind} job is already running")
            job_id = uuid.uuid4().hex[:12]
            self.jobs[job_id] = {
                "job_id": job_id, "actor": actor, "kind": kind, "status": "queued",
                "completed": 0, "total": total, "error": None,
            }
            self.active[key] = job_id

        def run() -> None:
            self._update(job_id, status="running")
            try:
                worker(job_id)
                self._update(job_id, status="completed")
            except Exception as exc:
                self._update(job_id, status="failed", error=str(exc))
            finally:
                with self.lock:
                    if self.active.get(key) == job_id:
                        self.active.pop(key, None)

        threading.Thread(target=run, name=f"craft-{kind}-{job_id}", daemon=True).start()
        return self.status(actor, job_id)

    def _update(self, job_id: str, **values: Any) -> None:
        with self.lock:
            self.jobs[job_id].update(values)

    def status(self, actor: str, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["actor"] != actor:
                raise ValueError("craft job not found")
            return {key: value for key, value in job.items() if key != "actor"}

    def queue_canvas(self, actor: str, strokes: list[dict[str, Any]], interval_ms: int = 360) -> dict[str, Any]:
        if not 1 <= len(strokes) <= 12:
            raise ValueError("queue 1 to 12 strokes at a time")
        interval = max(180, min(1200, int(interval_ms))) / 1000
        clean: list[dict[str, Any]] = []
        for stroke in strokes:
            points = stroke.get("points") or []
            if not 1 <= len(points) <= 14:
                raise ValueError("each stroke needs 1 to 14 hand target points")
            clean.append({
                "points": points,
                "color": str(stroke.get("color") or "#33423b"),
                "width": float(stroke.get("width") or 8),
                "opacity": float(stroke.get("opacity") or 1),
                "mode": str(stroke.get("mode") or "draw"),
                "brush": str(stroke.get("brush") or "pen"),
            })

        def worker(job_id: str) -> None:
            for index, stroke in enumerate(clean, 1):
                self.canvas.select_color(actor, stroke["color"])
                self.canvas.draw_path(actor, naturalize=True, **stroke)
                self._update(job_id, completed=index)
                if index < len(clean):
                    time.sleep(interval)

        return self._start(actor, "canvas", len(clean), worker)

    def continue_bead_plan(self, actor: str, board_id: str, handfuls: int = 4, interval_ms: int = 520) -> dict[str, Any]:
        handfuls = max(1, min(8, int(handfuls)))
        interval = max(250, min(1500, int(interval_ms))) / 1000
        board = self.beads.get(actor, board_id)
        session = board.get("work_session") or {}
        remaining = list(session.get("remaining") or [])
        if not remaining:
            raise ValueError("this board has no unfinished work plan")
        selected: list[dict[str, Any]] = []
        batches: list[list[dict[str, Any]]] = []
        for step in remaining:
            needs_new = not batches or len(batches[-1]) >= 5 or batches[-1][0]["color"] != step["color"]
            if needs_new:
                if len(batches) >= handfuls:
                    break
                batches.append([])
            batches[-1].append(step)
            selected.append(step)

        def worker(job_id: str) -> None:
            placed = 0
            for index, batch in enumerate(batches):
                self.beads.select_color(actor, board_id, batch[0]["color"])
                self.beads.place(actor, board_id, batch)
                placed += len(batch)
                self._update(job_id, completed=placed)
                if index + 1 < len(batches):
                    time.sleep(interval)

        result = self._start(actor, "beads", len(selected), worker)
        result["board_id"] = board_id
        result["handfuls"] = len(batches)
        return result
