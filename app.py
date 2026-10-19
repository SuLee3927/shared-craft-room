import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from shared_craft_room.server import app

__all__ = ["app"]
