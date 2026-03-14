"""
game_service.py — Framework-agnostic game turn processor.
Called by both the REST action endpoint and the WebSocket handler.
Returns a structured dict that both can serialise into their respective formats.
"""
from typing import Optional

from .session_store import SessionContainer
from . import async_dm as adm


async def process_action(container: SessionContainer, raw_action: str) -> dict:
    """
    Run one full game turn:
      1. Parse player intent
      2. Resolve mechanics (dice, combat, skill checks)
      3. Mutate world state
      4. Call DM agent asynchronously
      5. Return a result dict consumed by routers

    Returns a dict with keys:
        intent_type, mechanic_result, dm_response, player_hp, player_max_hp,
        player_location, in_combat, combat, events
    """
    async with container.action_lock:
        return await _process(container, raw_action)


async def _process(container: SessionContainer, raw_action: str) -> dict:
    sm     = container.state_manager
    cm     = container.combat_manager
    parser = container.intent_parser
    dm     = container.dm_agent
    player = sm.world.player

    parsed      = parser.parse(raw_action)
    intent_type = parsed["type"]
    mech_result = ""
    events: list[str] = []

    # ── META ──────────────────────────────────────────────────────────────────
    if intent_type == "meta":
        cmd = parsed.get("meta_command", "")
        mech_result = f"meta:{cmd}"
        # Meta commands don't call the DM; caller handles display
        return _build_result(
            container, parsed, mech_result, f"[{cmd}]", events
        )

    # ── Combat initiation ─────────────────────────────────────────────────────
    if (
        intent_type == "initiative"
        or (intent_type == "attack" and not cm.is_in_combat())
    ) and sm.world.get_hostile_npcs():
        hostile_ids = [n.npc_id for n in sm.world.get_hostile_npcs()]
        cm.initiate_combat(hostile_ids)
        mech_result = "Combat initiated."
        events.append("combat_started")

    # ── Active combat ─────────────────────────────────────────────────────────
    if cm.is_in_combat() and intent_type not in ("meta", "initiative"):
        turn_result = cm.process_player_turn(parsed)
        mech_result = turn_result.mechanical_details
        sm.world.log_action(raw_action, turn_result.narrative_summary)

        end_state = cm.check_combat_end()

        if end_state == "player_victory":
            post = cm.resolve_post_combat()
            events.append("combat_victory")
            events.append(f"xp_gained:{post.xp_gained}")
            if post.leveled_up:
                events.append(f"level_up:{post.new_level}")
                container.status = "active"
            mech_result += f" | +{post.xp_gained} XP"

        elif end_state == "player_defeat":
            container.status = "game_over"
            events.append("player_defeated")

        elif end_state == "player_unconscious":
            events.append("player_unconscious")
            mech_result += _handle_death_save(container, events)

        else:
            # NPCs act
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

    # ── Out-of-combat ─────────────────────────────────────────────────────────
    elif not cm.is_in_combat():
        if intent_type == "skill_check":
            mech_result = sm.resolve_mechanic(raw_action, parsed)
            sm.world.log_action(raw_action, mech_result)
        elif intent_type == "use_item":
            mech_result = _use_item(parsed, player)
            sm.world.log_action(raw_action, mech_result)
        else:
            sm.world.log_action(raw_action, "Narrative action.")
            mech_result = "Action requires narrative resolution."

    # ── DM narration (async, non-blocking) ────────────────────────────────────
    action_log = _build_action_log(parsed, raw_action, mech_result)
    context    = sm.build_context_payload()
    try:
        dm_response = await adm.generate_response(dm, context, action_log)
        if dm_response:
            sm.world.current_scene = dm_response[:200]
    except Exception as exc:
        dm_response = f"[DM unavailable: {exc}]"

    return _build_result(container, parsed, mech_result, dm_response, events)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _handle_death_save(container: SessionContainer, events: list[str]) -> str:
    from src.mechanics import EntitySnapshot
    player   = container.state_manager.world.player
    snapshot = EntitySnapshot(**player.to_snapshot_dict())
    result   = container.mechanics.resolve_death_save(snapshot)

    if result.nat_20:
        player.hp = 1
        player.death_saves = {"successes": 0, "failures": 0}
        events.append("death_save_nat20")
    elif result.nat_1:
        player.death_saves["failures"] = min(3, player.death_saves.get("failures", 0) + 2)
        events.append("death_save_nat1")
    elif result.success:
        player.death_saves["successes"] = player.death_saves.get("successes", 0) + 1
        events.append("death_save_success")
    else:
        player.death_saves["failures"] = player.death_saves.get("failures", 0) + 1
        events.append("death_save_failure")

    return f" | {result.mechanical_summary()}"


def _use_item(parsed: dict, player) -> str:
    from src.mechanics import DieRoll
    item_name = parsed.get("item_name", "healing_potion")
    entry = next(
        (i for i in player.inventory if i.get("type") == item_name and i.get("qty", 0) > 0),
        None,
    )
    if not entry:
        return f"No {item_name.replace('_', ' ')} in inventory."
    if item_name == "healing_potion":
        heal = DieRoll("2d4+2").roll()
        old_hp = player.hp
        player.hp = min(player.max_hp, player.hp + heal.total)
        entry["qty"] -= 1
        if entry["qty"] <= 0:
            player.inventory.remove(entry)
        return f"Drank healing potion. Healed {heal.total} HP. ({old_hp} → {player.hp})"
    return f"Used {item_name.replace('_', ' ')}."


def _build_action_log(parsed: dict, raw_input: str, mech_result: str) -> str:
    parts = [f"Player Intent: [{parsed.get('type', 'narrative')}]", f"Input: '{raw_input}'"]
    if mech_result and mech_result != "Action requires narrative resolution.":
        parts.append(f"System Result: {mech_result}")
    if parsed.get("target"):
        parts.append(f"Target: {parsed['target']}")
    if parsed.get("spell_name"):
        parts.append(f"Spell: {parsed['spell_name']}")
    return " | ".join(parts)


def _build_result(
    container: SessionContainer,
    parsed: dict,
    mech_result: str,
    dm_response: str,
    events: list[str],
) -> dict:
    sm     = container.state_manager
    player = sm.world.player
    cs     = sm.world.combat_state

    combat_out: Optional[dict] = None
    if cs and cs.active:
        combat_out = {
            "active": True,
            "round": cs.round_number,
            "current_actor": cs.current_actor_id(),
            "initiative_order": cs.initiative_order,
        }

    return {
        "intent_type":      parsed.get("type", "narrative"),
        "mechanic_result":  mech_result,
        "dm_response":      dm_response,
        "player_hp":        player.hp,
        "player_max_hp":    player.max_hp,
        "player_location":  player.location,
        "in_combat":        container.combat_manager.is_in_combat(),
        "combat":           combat_out,
        "events":           events,
    }
