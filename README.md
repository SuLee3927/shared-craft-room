# Shared Craft Room

A cozy shared craft room where a human and an AI can draw together, place perler beads one handful at a time, finish the work, and display it in a little gallery.

The project includes a mobile web UI and a Stateless Streamable HTTP MCP endpoint. It is a standalone craft app: there are no diary, chat-memory, or private relationship features.

## Features

- Shared portrait or landscape sketchbook with live strokes, color presence, naturalized AI paths, brushes, fill, and actor-scoped undo
- Perler boards in `together`, `separate`, and hidden `gift` modes
- MARD color codes, per-participant bead inventories, reference patterns, resumable work plans, and 1–5 bead handfuls
- Hands-on cover, heat, iron, cool, and lift workflow
- Finished-work decoration with transparent PNG export, pouch presentation, outlines, and shadows
- Shared gallery with picture frames, a tabletop stand, and size-aware hanging pouch slots
- Participant-specific web and MCP access keys stored only as SHA-256 hashes
- Generated anime-style room artwork bundled locally; no external image CDN is required

## Quick start

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export CRAFT_ADMIN_KEY="replace-with-a-long-random-secret"
shared-craft-room
```

Open `http://127.0.0.1:8000/setup/<CRAFT_ADMIN_KEY>/` and create at least two participants. The setup page returns a private room URL and MCP URL for each participant. An access key is shown only when it is created or rotated.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CRAFT_ADMIN_KEY` | empty | Required secret for participant setup |
| `CRAFT_DATA_DIR` | `data` | Persistent JSON and PNG data directory |
| `CRAFT_PUBLIC_URL` | request origin | Public base URL returned by setup |
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `8000` | Listen port |

The app does not automatically load `.env`; inject variables through your shell or hosting platform.

## MCP tools

Drawing: `new_canvas`, `get_canvas_snapshot`, `select_canvas_color`, `draw_path`, `brush_stroke`, `fill_region`, `undo_canvas`, `export_image`, `queue_canvas_strokes`.

Perler beads: `list_bead_boards`, `new_bead_board`, `open_bead_board`, `select_bead_color`, `set_bead_work_plan`, `pin_bead_reference`, `place_beads`, `continue_bead_work`, `take_bead`, `refill_beads`, `get_bead_snapshot`, `reveal_bead_gift`, `work_bead_finish`. Use `get_craft_job` only when a client needs explicit completion status.

The two queue tools are quota-friendly: one MCP call schedules multiple human-scale actions, while the server still publishes every stroke or five-bead handful separately for the live web UI.

Access keys live in the MCP URL rather than tool arguments. Treat room and MCP URLs as passwords and avoid logging or sharing them.

## Test

```bash
python3 -m pytest -q
```

## Deployment

Run behind HTTPS and persist `CRAFT_DATA_DIR`. A minimal command is:

```bash
uvicorn shared_craft_room.server:app --host 0.0.0.0 --port 8000
```

The bundled room backgrounds are WebP to keep first-load size small. User-created works remain PNG to preserve transparency.

## Privacy

This repository contains no production database, participant keys, private artwork, or server-specific launcher. The `data/` directory is ignored by Git.

## License

[MIT](LICENSE)
