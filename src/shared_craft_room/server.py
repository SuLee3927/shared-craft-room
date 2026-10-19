from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from .beads import BeadBoards
from .canvas import SharedCanvas
from .gallery import CraftGallery
from .identity import IdentityStore


DATA_DIR = Path(os.environ.get("CRAFT_DATA_DIR", "data"))
STATIC_DIR = Path(__file__).with_name("static")
ADMIN_KEY = os.environ.get("CRAFT_ADMIN_KEY", "")
DATA_DIR.mkdir(parents=True, exist_ok=True)

identities = IdentityStore(DATA_DIR / "participants.json")
canvas = SharedCanvas(DATA_DIR / "canvas.json")
beads = BeadBoards(DATA_DIR / "beads.json")
gallery = CraftGallery(DATA_DIR / "gallery.json")
logger = logging.getLogger("shared_craft_room")

MCP_INSTRUCTIONS = (
    "This is a shared hands-on craft room. Before drawing, inspect the canvas snapshot and "
    "select a color. Draw with several natural pen-down strokes rather than a single computed "
    "shape. For perler beads, select a color before each run and place only 1 to 5 beads per "
    "call so the other participant can watch the work happen."
)

POINT = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}, "required": ["x", "y"], "additionalProperties": False}
BEAD = {"type": "object", "properties": {"x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}, "color": {"type": "string"}}, "required": ["x", "y", "color"], "additionalProperties": False}

TOOLS = [
    {"name": "new_canvas", "description": "Start a fresh shared portrait or landscape drawing page.", "inputSchema": {"type": "object", "properties": {"background": {"type": "string", "default": "#fffdf7"}, "orientation": {"type": "string", "enum": ["portrait", "landscape"], "default": "portrait"}}, "additionalProperties": False}},
    {"name": "get_canvas_snapshot", "description": "View the current shared canvas as a PNG before drawing.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "select_canvas_color", "description": "Show the other participant which drawing color you selected.", "inputSchema": {"type": "object", "properties": {"color": {"type": "string"}}, "required": ["color"], "additionalProperties": False}},
    {"name": "draw_path", "description": "Draw one natural pen-down stroke with at most 14 hand target points, then lift the pen.", "inputSchema": {"type": "object", "properties": {"points": {"type": "array", "minItems": 1, "maxItems": 14, "items": POINT}, "color": {"type": "string", "default": "#33423b"}, "width": {"type": "number", "minimum": 1, "maximum": 100, "default": 8}, "opacity": {"type": "number", "minimum": 0.05, "maximum": 1, "default": 1}, "mode": {"type": "string", "enum": ["draw", "erase"], "default": "draw"}, "brush": {"type": "string", "enum": ["pencil", "pen", "marker", "brush"], "default": "pen"}}, "required": ["points"], "additionalProperties": False}},
    {"name": "brush_stroke", "description": "Alias of draw_path for one natural brush stroke.", "inputSchema": {"type": "object", "properties": {"points": {"type": "array", "minItems": 1, "maxItems": 14, "items": POINT}, "color": {"type": "string", "default": "#33423b"}, "width": {"type": "number", "default": 8}, "opacity": {"type": "number", "default": 1}, "brush": {"type": "string", "enum": ["pencil", "pen", "marker", "brush"], "default": "brush"}}, "required": ["points"], "additionalProperties": False}},
    {"name": "fill_region", "description": "Fill one closed drawing region at a point.", "inputSchema": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "color": {"type": "string"}}, "required": ["x", "y", "color"], "additionalProperties": False}},
    {"name": "undo_canvas", "description": "Undo your own most recent stroke.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "export_image", "description": "Return the current shared drawing as PNG.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "list_bead_boards", "description": "List bead boards visible to you.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "new_bead_board", "description": "Take a new empty pegboard in together, separate, or gift mode.", "inputSchema": {"type": "object", "properties": {"title": {"type": "string", "maxLength": 40}, "mode": {"type": "string", "enum": ["together", "separate", "gift"]}, "size": {"type": "integer", "enum": [8, 12, 16, 24, 32, 48, 64]}}, "required": ["title", "mode", "size"], "additionalProperties": False}},
    {"name": "open_bead_board", "description": "Inspect a bead board, its coordinates, inventories, and unfinished plan.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}}, "required": ["board_id"], "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "select_bead_color", "description": "Select a MARD color by code, Chinese name, or hex before placing beads.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "color": {"type": "string"}}, "required": ["board_id", "color"], "additionalProperties": False}},
    {"name": "set_bead_work_plan", "description": "Save a resumable bead plan and pin its generated reference image.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "title": {"type": "string"}, "beads": {"type": "array", "minItems": 1, "maxItems": 512, "items": BEAD}}, "required": ["board_id", "beads"], "additionalProperties": False}},
    {"name": "pin_bead_reference", "description": "Alias for set_bead_work_plan; pins the pattern without placing beads.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "title": {"type": "string"}, "beads": {"type": "array", "minItems": 1, "maxItems": 512, "items": BEAD}}, "required": ["board_id", "beads"], "additionalProperties": False}},
    {"name": "place_beads", "description": "Place one visible handful of 1 to 5 beads.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "beads": {"type": "array", "minItems": 1, "maxItems": 5, "items": BEAD}}, "required": ["board_id", "beads"], "additionalProperties": False}},
    {"name": "take_bead", "description": "Take exactly one bead back from the board.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["board_id", "x", "y"], "additionalProperties": False}},
    {"name": "refill_beads", "description": "Refill one exhausted color with 80 beads.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "color": {"type": "string"}}, "required": ["board_id", "color"], "additionalProperties": False}},
    {"name": "get_bead_snapshot", "description": "View the current bead board as PNG.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}}, "required": ["board_id"], "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
    {"name": "reveal_bead_gift", "description": "Reveal a gift board to the other participant.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}}, "required": ["board_id"], "additionalProperties": False}},
    {"name": "work_bead_finish", "description": "Perform one finishing step: cover, uncover, heat, start_iron, finish_iron, or lift.", "inputSchema": {"type": "object", "properties": {"board_id": {"type": "string"}, "action": {"type": "string", "enum": ["cover", "uncover", "heat", "start_iron", "finish_iron", "lift"]}}, "required": ["board_id", "action"], "additionalProperties": False}},
]


def actor_for(request: Request) -> str | None:
    return identities.authenticate(str(request.path_params.get("access_key") or ""))


def error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def admin_ok(request: Request) -> bool:
    return bool(ADMIN_KEY) and hmac.compare_digest(str(request.path_params.get("admin_key") or ""), ADMIN_KEY)


def public_base(request: Request) -> str:
    configured = os.environ.get("CRAFT_PUBLIC_URL", "").rstrip("/")
    return configured or str(request.base_url).rstrip("/")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "shared-craft-room", "version": "0.1.0"})


async def setup_page(request: Request) -> Response:
    if not admin_ok(request):
        return PlainTextResponse("Not found", status_code=404)
    return HTMLResponse("""<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Shared Craft Room Setup</title><style>body{font:16px system-ui;max-width:620px;margin:40px auto;padding:20px;background:#fff7ef;color:#493c37}form{display:grid;gap:12px;padding:24px;border-radius:20px;background:white}input,select,button{font:inherit;padding:12px;border:1px solid #d7c4b8;border-radius:12px}button{background:#b8677c;color:white}</style><h1>Shared Craft Room</h1><form id=f><input name=id placeholder='participant id' required><input name=display_name placeholder='display name' required><select name=kind><option value=human>human</option><option value=ai>ai</option></select><button>Create participant</button><pre id=o></pre></form><script>f.onsubmit=async e=>{e.preventDefault();let b=Object.fromEntries(new FormData(f));let r=await fetch(location.pathname.replace('/setup/','/admin-api/participants/'),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});o.textContent=JSON.stringify(await r.json(),null,2)}</script>""")


async def admin_participants(request: Request) -> Response:
    if not admin_ok(request):
        return PlainTextResponse("Not found", status_code=404)
    try:
        if request.method == "GET":
            return JSONResponse({"ok": True, "participants": identities.list_participants()})
        data = await request.json()
        created = identities.create(data.get("id", ""), data.get("display_name", ""), data.get("kind", "human"))
        access_key = created["access_key"]
        root = public_base(request)
        return JSONResponse({"ok": True, **created, "room_url": f"{root}/room/{access_key}/", "mcp_url": f"{root}/mcp/{access_key}/"})
    except (json.JSONDecodeError, ValueError) as exc:
        return error(str(exc))


async def admin_rotate(request: Request) -> Response:
    if not admin_ok(request):
        return PlainTextResponse("Not found", status_code=404)
    try:
        raw = identities.rotate_key(str(request.path_params["participant_id"]))
        root = public_base(request)
        return JSONResponse({"ok": True, "access_key": raw, "room_url": f"{root}/room/{raw}/", "mcp_url": f"{root}/mcp/{raw}/"})
    except ValueError as exc:
        return error(str(exc), 404)


async def room_home(request: Request) -> Response:
    if actor_for(request) is None:
        return PlainTextResponse("Not found", status_code=404)
    return RedirectResponse(f"/room/{request.path_params['access_key']}/crafts/")


async def page(request: Request) -> Response:
    if actor_for(request) is None:
        return PlainTextResponse("Not found", status_code=404)
    page_name = request.url.path.rstrip("/").rsplit("/", 1)[-1]
    return FileResponse(STATIC_DIR / f"{page_name}.html", headers={"Cache-Control": "no-store"})


async def asset(request: Request) -> Response:
    if actor_for(request) is None:
        return PlainTextResponse("Not found", status_code=404)
    name = str(request.path_params.get("name") or "")
    path = STATIC_DIR / name
    if Path(name).name != name or not path.is_file():
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


async def api_canvas(request: Request) -> Response:
    actor = actor_for(request)
    if actor is None:
        return error("not found", 404)
    if request.method == "GET":
        canvas.touch(actor, "viewing")
        return JSONResponse({"ok": True, "canvas": canvas.state(), "presence": canvas.presence_for(actor), "me": identities.participant(actor), "participants": identities.list_participants()})
    try:
        data = await request.json()
        action = str(data.get("action") or "draw")
        if action == "draw":
            result = canvas.draw_path(actor, data.get("points") or [], color=str(data.get("color") or "#33423b"), width=float(data.get("width") or 8), opacity=float(data.get("opacity") or 1), mode=str(data.get("mode") or "draw"), brush=str(data.get("brush") or "pen"))
        elif action == "undo": result = canvas.undo(actor)
        elif action == "clear": result = canvas.clear(actor, str(data.get("background") or "#fffdf7"), data.get("width"), data.get("height"))
        elif action == "select_color": result = canvas.select_color(actor, str(data.get("color") or ""))
        else: return error("unknown canvas action")
        return JSONResponse({"ok": True, **result})
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return error(str(exc))


async def api_canvas_png(request: Request) -> Response:
    if actor_for(request) is None: return error("not found", 404)
    return Response(canvas.png_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


async def api_boards(request: Request) -> Response:
    actor = actor_for(request)
    if actor is None: return error("not found", 404)
    try:
        if request.method == "GET":
            return JSONResponse({"ok": True, "boards": beads.list_boards(actor), "me": identities.participant(actor)})
        data = await request.json()
        return JSONResponse({"ok": True, "board": beads.create(actor, str(data.get("title") or ""), str(data.get("mode") or "together"), int(data.get("size") or 16))})
    except (json.JSONDecodeError, TypeError, ValueError) as exc: return error(str(exc))


async def api_board(request: Request) -> Response:
    actor, board_id = actor_for(request), str(request.path_params.get("board_id") or "")
    if actor is None: return error("not found", 404)
    try:
        if request.method == "GET":
            return JSONResponse({"ok": True, "board": beads.get(actor, board_id), "presence": beads.presence_for(actor, board_id), "me": identities.participant(actor), "participants": identities.list_participants()})
        if request.method == "DELETE": return JSONResponse({"ok": True, **beads.delete(actor, board_id)})
        data, result = await request.json(), None
        action = str(data.get("action") or "")
        if action == "place": result = beads.place(actor, board_id, data.get("beads") or [])
        elif action == "select": result = beads.select_color(actor, board_id, str(data.get("color") or ""))
        elif action == "take": result = beads.take(actor, board_id, int(data.get("x")), int(data.get("y")))
        elif action == "refill": result = beads.refill(actor, board_id, str(data.get("color") or ""))
        elif action == "reveal": result = beads.reveal(actor, board_id)
        elif action == "reference": result = beads.set_reference(actor, board_id, data.get("data_url"))
        elif action == "decoration": result = beads.save_decoration(actor, board_id, str(data.get("data_url") or ""), str(data.get("piece_data_url") or ""), bool(data.get("has_pouch")))
        elif action in {"cover", "uncover", "heat", "start_iron", "finish_iron", "lift"}: result = beads.craft(actor, board_id, action)
        else: return error("unknown bead-board action")
        return JSONResponse({"ok": True, **result})
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc: return error(str(exc))


async def api_board_png(request: Request) -> Response:
    actor = actor_for(request)
    if actor is None: return error("not found", 404)
    try: return Response(beads.png_bytes(actor, str(request.path_params["board_id"])), media_type="image/png", headers={"Cache-Control": "no-store"})
    except ValueError as exc: return error(str(exc), 404)


def participant_names(actor_ids: list[str]) -> list[str]:
    names = {item["id"]: item["display_name"] for item in identities.list_participants()}
    return [names.get(actor, "共同作者") for actor in dict.fromkeys(actor_ids)]


async def api_gallery(request: Request) -> Response:
    actor = actor_for(request)
    if actor is None: return error("not found", 404)
    try:
        if request.method == "GET": return JSONResponse({"ok": True, "items": gallery.list_items(), "me": identities.participant(actor)})
        data, kind = await request.json(), ""
        kind = str(data.get("kind") or "")
        if kind == "sketch":
            state = canvas.state()
            if not state.get("strokes"): raise ValueError("draw something before adding it to the gallery")
            actors = [str(stroke.get("actor")) for stroke in state["strokes"] if stroke.get("actor")]
            item = gallery.add(kind, str(data.get("title") or "Shared drawing"), actor, participant_names(actors), canvas.png_bytes())
        elif kind == "bead":
            board_id = str(data.get("source_id") or "")
            board = beads.get(actor, board_id)
            if not board.get("craft", {}).get("decorated"): raise ValueError("save the decorated work first")
            actors = [str(bead.get("actor")) for bead in board.get("cells", {}).values() if bead.get("actor")]
            columns, rows = int(data.get("piece_columns") or 0), int(data.get("piece_rows") or 0)
            if columns < 1 or rows < 1: raise ValueError("finished work size is missing")
            item = gallery.add(kind, str(data.get("title") or board["title"]), actor, participant_names(actors), beads.decorated_bytes(actor, board_id), board_id, "decorated", beads.display_piece_bytes(actor, board_id), (columns, rows), bool(board.get("craft", {}).get("has_pouch")))
        else: raise ValueError("choose sketch or bead")
        return JSONResponse({"ok": True, "item": item})
    except (json.JSONDecodeError, TypeError, ValueError) as exc: return error(str(exc))


async def api_gallery_item(request: Request) -> Response:
    if actor_for(request) is None: return error("not found", 404)
    item_id = str(request.path_params.get("item_id") or "")
    try:
        if request.method == "DELETE": return JSONResponse({"ok": True, **gallery.remove(item_id)})
        data = await request.json()
        if data.get("action") == "feature": return JSONResponse({"ok": True, "items": gallery.feature(item_id, None if data.get("slot") is None else int(data["slot"]))})
        if data.get("action") == "hang": return JSONResponse({"ok": True, "items": gallery.hang(item_id, bool(data.get("enabled", True)))})
        return JSONResponse({"ok": True, "items": gallery.move(item_id, str(data.get("direction") or ""))})
    except (json.JSONDecodeError, ValueError) as exc: return error(str(exc), 404 if "not found" in str(exc) else 400)


async def gallery_image(request: Request) -> Response:
    if actor_for(request) is None: return error("not found", 404)
    try:
        path = gallery.display_image_path(str(request.path_params["item_id"])) if request.url.path.endswith("/display.png") else gallery.image_path(str(request.path_params["item_id"]))
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
    except ValueError as exc: return error(str(exc), 404)


def call_tool(actor: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    dispatch = {
        "new_canvas": lambda background="#fffdf7", orientation="portrait": canvas.clear(actor, background, *((800, 1200) if orientation == "portrait" else (1200, 800))),
        "get_canvas_snapshot": lambda: canvas.snapshot_payload(actor), "export_image": lambda: canvas.snapshot_payload(actor),
        "select_canvas_color": lambda color: canvas.select_color(actor, color),
        "draw_path": lambda **kw: canvas.draw_path(actor, naturalize=True, **kw),
        "brush_stroke": lambda **kw: canvas.draw_path(actor, naturalize=True, **kw),
        "fill_region": lambda x, y, color: canvas.draw_path(actor, [{"x": x, "y": y}], color=color, mode="fill"),
        "undo_canvas": lambda: canvas.undo(actor), "list_bead_boards": lambda: {"boards": beads.list_boards(actor)},
        "new_bead_board": lambda **kw: beads.create(actor, **kw), "open_bead_board": lambda board_id: beads.get(actor, board_id),
        "select_bead_color": lambda board_id, color: beads.select_color(actor, board_id, color),
        "set_bead_work_plan": lambda board_id, beads, title="": globals()["beads"].set_work_plan(actor, board_id, beads, title),
        "pin_bead_reference": lambda board_id, beads, title="": globals()["beads"].set_work_plan(actor, board_id, beads, title),
        "place_beads": lambda board_id, beads: globals()["beads"].place(actor, board_id, beads),
        "take_bead": lambda board_id, x, y: beads.take(actor, board_id, x, y), "refill_beads": lambda board_id, color: beads.refill(actor, board_id, color),
        "get_bead_snapshot": lambda board_id: {"board_id": board_id, "_image_bytes": beads.png_bytes(actor, board_id)},
        "reveal_bead_gift": lambda board_id: beads.reveal(actor, board_id), "work_bead_finish": lambda board_id, action: beads.craft(actor, board_id, action),
    }
    if name not in dispatch: raise KeyError(name)
    return dispatch[name](**args)


def rpc_result(request_id: Any, result: Any) -> dict[str, Any]: return {"jsonrpc": "2.0", "id": request_id, "result": result}
def rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]: return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_mcp(actor: str, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0": return rpc_error(None, -32600, "Invalid Request")
    request_id, method = message.get("id"), message.get("method")
    if request_id is None: return None
    if method == "initialize": return rpc_result(request_id, {"protocolVersion": (message.get("params") or {}).get("protocolVersion") or "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "Shared Craft Room", "version": "0.1.0"}, "instructions": MCP_INSTRUCTIONS})
    if method == "ping": return rpc_result(request_id, {})
    if method == "tools/list": return rpc_result(request_id, {"tools": TOOLS})
    if method != "tools/call": return rpc_error(request_id, -32601, "Method not found")
    params, payload = message.get("params") or {}, None
    try:
        payload = call_tool(actor, str(params.get("name") or ""), params.get("arguments") or {})
        image = payload.pop("_image_base64", None)
        if payload.get("_image_bytes"): image = base64.b64encode(payload.pop("_image_bytes")).decode("ascii")
        content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
        if image: content.append({"type": "image", "data": image, "mimeType": "image/png"})
        return rpc_result(request_id, {"content": content})
    except KeyError: return rpc_error(request_id, -32602, "Unknown tool")
    except (TypeError, ValueError) as exc: return rpc_result(request_id, {"content": [{"type": "text", "text": json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False)}], "isError": True})
    except Exception:
        reference = uuid.uuid4().hex[:12]
        logger.exception("tool failed: %s", reference)
        return rpc_result(request_id, {"content": [{"type": "text", "text": json.dumps({"ok": False, "message": f"tool failed ({reference})"})}], "isError": True})


async def mcp(request: Request) -> Response:
    actor = actor_for(request)
    if actor is None: return PlainTextResponse("Not found", status_code=404)
    try: message = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError): return JSONResponse(rpc_error(None, -32700, "Parse error"))
    response = handle_mcp(actor, message)
    return Response(status_code=202) if response is None else JSONResponse(response)


routes = [
    Route("/", health), Route("/health", health), Route("/setup/{admin_key}/", setup_page),
    Route("/admin-api/participants/{admin_key}/", admin_participants, methods=["GET", "POST"]),
    Route("/admin-api/participants/{admin_key}/{participant_id}/rotate", admin_rotate, methods=["POST"]),
    Route("/room/{access_key}/", room_home), Route("/room/{access_key}/sketch/", page, name="sketch", methods=["GET"]), Route("/room/{access_key}/beads/", page, name="beads", methods=["GET"]), Route("/room/{access_key}/crafts/", page, name="crafts", methods=["GET"]), Route("/room/{access_key}/assets/{name}", asset),
    Route("/api/{access_key}/canvas", api_canvas, methods=["GET", "POST"]), Route("/api/{access_key}/canvas.png", api_canvas_png),
    Route("/api/{access_key}/bead-boards", api_boards, methods=["GET", "POST"]), Route("/api/{access_key}/bead-boards/{board_id}.png", api_board_png), Route("/api/{access_key}/bead-boards/{board_id}", api_board, methods=["GET", "POST", "DELETE"]),
    Route("/api/{access_key}/gallery", api_gallery, methods=["GET", "POST"]), Route("/api/{access_key}/gallery/{item_id}/display.png", gallery_image), Route("/api/{access_key}/gallery/{item_id}.png", gallery_image), Route("/api/{access_key}/gallery/{item_id}", api_gallery_item, methods=["POST", "DELETE"]),
    Route("/mcp/{access_key}", mcp, methods=["POST"]), Route("/mcp/{access_key}/", mcp, methods=["POST"]),
]
app = Starlette(routes=routes)


def main() -> None:
    import uvicorn
    uvicorn.run("shared_craft_room.server:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), access_log=False)


if __name__ == "__main__": main()
