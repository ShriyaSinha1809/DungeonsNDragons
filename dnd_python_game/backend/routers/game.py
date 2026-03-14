"""
routers/game.py — Core game loop and world state endpoints.

POST  /api/sessions/{id}/action   Process one player action (full pipeline)
GET   /api/sessions/{id}/state    Full world state snapshot
GET   /api/sessions/{id}/quests   Active quest list
"""
from fastapi import APIRouter, HTTPException, Request

from ..models import ActionRequest, ActionResponse, GameStateResponse, CombatOut, NPCSummary, QuestOut
from ..session_store import SessionStore
from ..game_service import process_action
from ..routers.characters import player_to_sheet

router = APIRouter()


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _combat_out(cs) -> CombatOut | None:
    if not cs or not cs.active:
        return None
    return CombatOut(
        active=True,
        round=cs.round_number,
        current_actor=cs.current_actor_id(),
        initiative_order=cs.initiative_order,
    )


@router.post("/sessions/{session_id}/action", response_model=ActionResponse)
async def player_action(session_id: str, body: ActionRequest, request: Request):
    """
    Main game loop endpoint.
    Runs: intent parse → mechanic resolution → state mutation → DM narration.
    """
    store = _store(request)
    c = store.get(session_id)
    if not c:
        raise HTTPException(404, detail="Session not found.")
    if c.status == "game_over":
        raise HTTPException(400, detail="This session has ended.")
    if not c.state_manager.world.player:
        raise HTTPException(400, detail="No character created yet.")

    result = await process_action(c, body.action)

    return ActionResponse(
        session_id=session_id,
        intent_type=result["intent_type"],
        mechanic_result=result["mechanic_result"],
        dm_response=result["dm_response"],
        player_hp=result["player_hp"],
        player_max_hp=result["player_max_hp"],
        player_location=result["player_location"],
        in_combat=result["in_combat"],
        combat=CombatOut(**result["combat"]) if result["combat"] else None,
        events=result["events"],
    )


@router.get("/sessions/{session_id}/state", response_model=GameStateResponse)
def get_state(session_id: str, request: Request):
    """Return a full snapshot of the world state."""
    c = _store(request).get(session_id)
    if not c:
        raise HTTPException(404, detail="Session not found.")
    if not c.state_manager.world.player:
        raise HTTPException(400, detail="No character created yet.")

    sm = c.state_manager

    npc_summaries = {
        nid: NPCSummary(
            kind=npc.kind,
            hp=npc.hp,
            max_hp=npc.max_hp,
            ac=npc.ac,
            location=npc.location,
            hostile=npc.hostile,
            alive=npc.is_alive(),
            conditions=npc.conditions,
        )
        for nid, npc in sm.world.npcs.items()
    }

    quests = [
        QuestOut(
            title=q.title,
            description=q.description,
            objectives=q.objectives,
            completed=q.completed,
        )
        for q in sm.world.active_quests
    ]

    return GameStateResponse(
        session_id=session_id,
        status=c.status,
        scene=sm.world.current_scene,
        player=player_to_sheet(sm.world.player),
        npcs=npc_summaries,
        quests=quests,
        turn_history=sm.world.turn_history,
        combat=_combat_out(sm.world.combat_state),
    )


@router.get("/sessions/{session_id}/quests", response_model=list[QuestOut])
def get_quests(session_id: str, request: Request):
    """Return active quest list for the session."""
    c = _store(request).get(session_id)
    if not c:
        raise HTTPException(404, detail="Session not found.")
    return [
        QuestOut(
            title=q.title,
            description=q.description,
            objectives=q.objectives,
            completed=q.completed,
        )
        for q in c.state_manager.world.active_quests
    ]
