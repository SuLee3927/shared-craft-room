from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared_craft_room.identity import IdentityStore


def test_access_keys_are_hashed_and_can_be_rotated(tmp_path):
    store = IdentityStore(tmp_path / "participants.json")
    created = store.create("alice", "Alice", "human")
    raw_key = created["access_key"]
    assert store.authenticate(raw_key) == "alice"
    assert raw_key not in (tmp_path / "participants.json").read_text()
    replacement = store.rotate_key("alice")
    assert store.authenticate(raw_key) is None
    assert store.authenticate(replacement) == "alice"


def test_participant_ids_are_validated(tmp_path):
    store = IdentityStore(tmp_path / "participants.json")
    with pytest.raises(ValueError):
        store.create("bad/id", "Alice")
