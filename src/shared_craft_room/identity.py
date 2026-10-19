from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IdentityStore:
    """Tiny participant registry. Raw access keys are never persisted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"participants": []})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data.get("participants"), list) else {"participants": []}
        except (OSError, json.JSONDecodeError):
            return {"participants": []}

    def _save(self, data: dict[str, Any]) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @staticmethod
    def _hash(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def list_participants(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {key: value for key, value in item.items() if key != "key_hash"}
                for item in self._load()["participants"]
            ]

    def participant(self, participant_id: str) -> dict[str, Any]:
        return next(
            (item for item in self.list_participants() if item["id"] == participant_id),
            None,
        ) or (_ for _ in ()).throw(ValueError("participant not found"))

    def create(self, participant_id: str, display_name: str, kind: str = "human") -> dict[str, Any]:
        participant_id = "-".join(str(participant_id).strip().lower().split())
        display_name = " ".join(str(display_name).split())[:40]
        if not participant_id or not all(char.isalnum() or char in "-_" for char in participant_id):
            raise ValueError("participant id may contain letters, numbers, hyphens, and underscores")
        if not display_name:
            raise ValueError("display name is required")
        if kind not in {"human", "ai"}:
            raise ValueError("kind must be human or ai")
        raw_key = secrets.token_urlsafe(32)
        with self.lock:
            data = self._load()
            if any(item["id"] == participant_id for item in data["participants"]):
                raise ValueError("participant id already exists")
            data["participants"].append({
                "id": participant_id,
                "display_name": display_name,
                "kind": kind,
                "key_hash": self._hash(raw_key),
                "created_at": now(),
            })
            self._save(data)
        return {"participant": self.participant(participant_id), "access_key": raw_key}

    def rotate_key(self, participant_id: str) -> str:
        raw_key = secrets.token_urlsafe(32)
        with self.lock:
            data = self._load()
            item = next((entry for entry in data["participants"] if entry["id"] == participant_id), None)
            if item is None:
                raise ValueError("participant not found")
            item["key_hash"] = self._hash(raw_key)
            self._save(data)
        return raw_key

    def authenticate(self, raw_key: str) -> str | None:
        if not raw_key:
            return None
        candidate = self._hash(raw_key)
        with self.lock:
            for item in self._load()["participants"]:
                if secrets.compare_digest(item.get("key_hash", ""), candidate):
                    return str(item["id"])
        return None
