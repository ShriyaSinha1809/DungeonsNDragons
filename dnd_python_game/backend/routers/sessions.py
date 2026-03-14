"""
routers/sessions.py — Session lifecycle endpoints.

POST   /api/sessions            Create a new game session + character
GET    /api/sessions            List all active session IDs
GET    /api/sessions/{id}       Get session metadata
DELETE /api/sessions/{id}       End a session
POST   /api/sessions/{id}/save  Persist world state to disk
POST   /api/sessions/{id}/load  Restore world state from disk
"""
from fastapi import APIRouter, HTTPException, Request

from ..models import SessionCreateRequest, SessionOut, SaveRequest
from ..session_store import SessionStore, SessionContainer
from ..character_service import build_player

router = APIRouter()


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _get_or_404(store: SessionStore, session_id: str) -> SessionContainer:
    c = store.get(session_id)
    if not c:
        raise HTTPException(404, detail=f"Session '{session_id}' not found.")
    return c


def _session_out(c: SessionContainer) -> SessionOut:
    player = c.state_manager.world.player
    return SessionOut(
        session_id=c.session_id,
        status=c.status,
        difficulty=c.config.difficulty,
        custom_rules=c.config.custom_rules or None,
        created_at=c.created_at,
        player_name=player.name if player else None,
        player_level=player.level if player else None,
        in_combat=c.combat_manager.is_in_combat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreateRequest, request: Request):
    """
    Create a session, build the character, spawn default NPCs, and start
    the DM session — all in one call.
    """
    store = _store(request)
    container = store.create(
        difficulty=body.difficulty,
        custom_rules=body.custom_rules or "",
    )

    sm = container.state_manager
    try:
        player = build_player(body.character, sm)
    except ValueError as exc:
        store.delete(container.session_id)
        raise HTTPException(422, detail=str(exc))

    sm.world.player = player
    sm.setup_default_quest()
    sm.spawn_npc("goblin", "goblin_1", location="Goblin Cave — Entrance")
    sm.spawn_npc("goblin", "goblin_2", location="Goblin Cave — Entrance")

    container.dm_agent.start_session(container.config, player)
    container.status = "active"

    return _session_out(container)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(request: Request):
    """Return metadata for all currently active sessions."""
    store = _store(request)
    return [_session_out(store.get(sid)) for sid in store.all_ids()]


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, request: Request):
    return _session_out(_get_or_404(_store(request), session_id))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request):
    if not _store(request).delete(session_id):
        raise HTTPException(404, detail=f"Session '{session_id}' not found.")


@router.post("/sessions/{session_id}/save")
def save_game(session_id: str, body: SaveRequest, request: Request):
    """Persist the current world state to a JSON file on disk."""
    store = _store(request)
    c = _get_or_404(store, session_id)
    if not c.state_manager.world.player:
        raise HTTPException(400, detail="No character to save.")
    try:
        path = store.save_to_disk(session_id, slot=body.slot)
        return {"saved": True, "path": path}
    except Exception as exc:
        raise HTTPException(500, detail=f"Save failed: {exc}")


@router.post("/sessions/{session_id}/load")
def load_game(session_id: str, body: SaveRequest, request: Request):
    """Restore a previously saved world state into the live session."""
    store = _store(request)
    _get_or_404(store, session_id)
    ok = store.load_from_disk(session_id, slot=body.slot)
    if not ok:
        raise HTTPException(404, detail="No save file found for this slot.")
    return {"loaded": True}
