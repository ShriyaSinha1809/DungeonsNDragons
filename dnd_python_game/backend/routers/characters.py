"""
routers/characters.py — Character sheet endpoints.

GET   /api/sessions/{id}/character   Full character sheet
GET   /api/sessions/{id}/inventory   Equipped items, inventory, gold, spell slots
"""
from fastapi import APIRouter, HTTPException, Request

from ..models import CharacterSheet, AbilityScoresOut, InventoryOut
from ..session_store import SessionStore

router = APIRouter()


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _get_player(session_id: str, store: SessionStore):
    c = store.get(session_id)
    if not c:
        raise HTTPException(404, detail="Session not found.")
    if not c.state_manager.world.player:
        raise HTTPException(404, detail="No character created yet.")
    return c.state_manager.world.player


def player_to_sheet(player) -> CharacterSheet:
    ab = player.ability_scores
    return CharacterSheet(
        name=player.name,
        race=player.race,
        char_class=player.char_class,
        level=player.level,
        hp=player.hp,
        max_hp=player.max_hp,
        ac=player.ac,
        xp=player.xp,
        gold=player.gold,
        location=player.location,
        ability_scores=AbilityScoresOut(
            strength=ab.str, dex=ab.dex, con=ab.con,
            intelligence=ab.int, wis=ab.wis, cha=ab.cha,
        ),
        proficient_skills=player.proficient_skills,
        proficient_saves=player.proficient_saves,
        equipped=player.equipped,
        inventory=player.inventory,
        spell_slots=player.spell_slots,
        known_spells=player.known_spells,
        conditions=player.conditions,
        death_saves=player.death_saves,
    )


@router.get("/sessions/{session_id}/character", response_model=CharacterSheet)
def get_character(session_id: str, request: Request):
    """Return the full character sheet for the session's player."""
    player = _get_player(session_id, _store(request))
    return player_to_sheet(player)


@router.get("/sessions/{session_id}/inventory", response_model=InventoryOut)
def get_inventory(session_id: str, request: Request):
    """Return equipped items, bag inventory, gold, and spell slot counts."""
    player = _get_player(session_id, _store(request))
    return InventoryOut(
        equipped=player.equipped,
        inventory=player.inventory,
        gold=player.gold,
        spell_slots=player.spell_slots,
    )
