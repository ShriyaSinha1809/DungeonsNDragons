"""
ws/dm_stream.py — WebSocket endpoint for streaming DM narrative responses.

Protocol
--------
Client → Server (JSON):
    {"action": "<player text>"}          Normal game action
    {"action": "ping"}                   Keep-alive

Server → Client (JSON frames):
    {"type": "mechanic_result",
     "data": "<dice/combat summary>"}    Sent before LLM call

    {"type": "token",
     "data": "<text chunk>"}             One per streamed LLM token

    {"type": "done",
     "dm_response": "<full narrative>",
     "mechanic_result": "...",
     "player_hp": int,
     "player_max_hp": int,
     "player_location": "...",
     "in_combat": bool,
     "events": [...]}                    Final frame, summarises the turn

    {"type": "error",
     "code": "SESSION_NOT_FOUND|GAME_OVER|NO_CHARACTER|INTERNAL",
     "detail": "..."}                    Sent on any failure
"""
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..session_store import SessionStore
from ..game_service import (
    _process as _sync_process,          # noqa: F401 – imported for mechanic resolution
    _build_action_log,
    _use_item,
    _handle_death_save,
    _build_result,
)
from .. import async_dm as adm

router = APIRouter()


async def _send(ws: WebSocket, payload: dict[str, Any]):
    await ws.send_text(json.dumps(payload))


@router.websocket("/ws/sessions/{session_id}/dm")
async def dm_stream(session_id: str, ws: WebSocket):
    """
    Streaming DM WebSocket.
    Runs the same turn pipeline as the REST action endpoint but streams
    LLM tokens in real-time instead of waiting for the full response.
    """
    store: SessionStore = ws.app.state.store

    container = store.get(session_id)
    if container is None:
        await ws.accept()
        await _send(ws, {"type": "error", "code": "SESSION_NOT_FOUND",
                         "detail": f"Session '{session_id}' not found."})
        await ws.close()
        return

    await ws.accept()

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action", "").strip()

            if not action:
                continue
            if action.lower() == "ping":
                await _send(ws, {"type": "pong"})
                continue

            # ── Guard checks ──────────────────────────────────────────────────
            if container.status == "game_over":
                await _send(ws, {"type": "error", "code": "GAME_OVER",
                                  "detail": "This session has ended."})
                continue
            if not container.state_manager.world.player:
                await _send(ws, {"type": "error", "code": "NO_CHARACTER",
                                  "detail": "No character created yet."})
                continue

            # ── Mechanic resolution (sync, fast) ──────────────────────────────
            async with container.action_lock:
                sm     = container.state_manager
                cm     = container.combat_manager
                parser = container.intent_parser
                player = sm.world.player

                parsed      = parser.parse(action)
                intent_type = parsed["type"]
                mech_result = ""
                events: list[str] = []

                # Meta commands: respond immediately, skip LLM
                if intent_type == "meta":
                    await _send(ws, {
                        "type": "done",
                        "dm_response": f"[{parsed.get('meta_command', '')}]",
                        "mechanic_result": f"meta:{parsed.get('meta_command')}",
                        "player_hp": player.hp,
                        "player_max_hp": player.max_hp,
                        "player_location": player.location,
                        "in_combat": cm.is_in_combat(),
                        "events": [],
                    })
                    continue

                # Combat initiation
                if (
                    intent_type == "initiative"
                    or (intent_type == "attack" and not cm.is_in_combat())
                ) and sm.world.get_hostile_npcs():
                    hostile_ids = [n.npc_id for n in sm.world.get_hostile_npcs()]
                    cm.initiate_combat(hostile_ids)
                    mech_result = "Combat initiated."
                    events.append("combat_started")

                # Active combat
                if cm.is_in_combat() and intent_type not in ("meta", "initiative"):
                    turn = cm.process_player_turn(parsed)
                    mech_result = turn.mechanical_details
                    sm.world.log_action(action, turn.narrative_summary)

                    end = cm.check_combat_end()
                    if end == "player_victory":
                        post = cm.resolve_post_combat()
                        events += ["combat_victory", f"xp_gained:{post.xp_gained}"]
                        if post.leveled_up:
                            events.append(f"level_up:{post.new_level}")
                        mech_result += f" | +{post.xp_gained} XP"
                    elif end == "player_defeat":
                        container.status = "game_over"
                        events.append("player_defeated")
                    elif end == "player_unconscious":
                        events.append("player_unconscious")
                        mech_result += _handle_death_save(container, events)
                    else:
                        npc_results = cm.process_npc_turns()
                        for r in npc_results:
                            sm.world.log_action(f"{r.actor_id} attacks", r.narrative_summary)
                            if r.damage_dealt > 0:
                                events.append(f"npc_hit:{r.actor_id}:{r.damage_dealt}")
                        cm.advance_turn()

                        end2 = cm.check_combat_end()
                        if end2 == "player_defeat":
                            container.status = "game_over"
                            events.append("player_defeated")
                        elif end2 == "player_unconscious":
                            events.append("player_unconscious")
                            mech_result += _handle_death_save(container, events)

                elif not cm.is_in_combat():
                    if intent_type == "skill_check":
                        mech_result = sm.resolve_mechanic(action, parsed)
                        sm.world.log_action(action, mech_result)
                    elif intent_type == "use_item":
                        mech_result = _use_item(parsed, player)
                        sm.world.log_action(action, mech_result)
                    else:
                        sm.world.log_action(action, "Narrative action.")
                        mech_result = "Action requires narrative resolution."

                # ── Emit mechanic result immediately ──────────────────────────
                await _send(ws, {"type": "mechanic_result", "data": mech_result})

                # ── Stream DM tokens ──────────────────────────────────────────
                action_log = _build_action_log(parsed, action, mech_result)
                context    = sm.build_context_payload()
                full_text  = ""

                try:
                    async for token in adm.generate_response_stream(
                        container.dm_agent, context, action_log
                    ):
                        full_text += token
                        await _send(ws, {"type": "token", "data": token})
                except Exception as exc:
                    full_text = f"[DM error: {exc}]"

                if full_text:
                    sm.world.current_scene = full_text[:200]

                # ── Final summary frame ───────────────────────────────────────
                cs = sm.world.combat_state
                await _send(ws, {
                    "type": "done",
                    "dm_response": full_text,
                    "mechanic_result": mech_result,
                    "player_hp": player.hp,
                    "player_max_hp": player.max_hp,
                    "player_location": player.location,
                    "in_combat": cm.is_in_combat(),
                    "combat": {
                        "active": True,
                        "round": cs.round_number,
                        "current_actor": cs.current_actor_id(),
                        "initiative_order": cs.initiative_order,
                    } if cs and cs.active else None,
                    "events": events,
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await _send(ws, {"type": "error", "code": "INTERNAL", "detail": str(exc)})
        except Exception:
            pass
