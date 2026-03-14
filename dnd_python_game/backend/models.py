"""
models.py — Pydantic request and response schemas for the D&D backend API.

Note: ability score fields use full-name Python attributes with short aliases
so the JSON API can still use "str", "int", etc. while avoiding Pydantic v2's
restriction on field names that shadow Python builtins (str, int).
"""
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


# ── Request Models ─────────────────────────────────────────────────────────────

class AbilityAssignment(BaseModel):
    """
    JSON keys use the standard D&D short names ("str", "dex", …).
    Python attributes use long names to avoid shadowing built-ins.
    """
    model_config = ConfigDict(populate_by_name=True)

    strength:     int = Field(..., ge=1, le=30, alias="str")
    dex:          int = Field(..., ge=1, le=30)
    con:          int = Field(..., ge=1, le=30)
    intelligence: int = Field(..., ge=1, le=30, alias="int")
    wis:          int = Field(..., ge=1, le=30)
    cha:          int = Field(..., ge=1, le=30)


class CharacterCreateRequest(BaseModel):
    name: str = Field("Aric Stormveil", min_length=1, max_length=50)
    race: str = Field("human", description="human | elf | halfling | dwarf")
    subrace: Optional[str] = Field(None, description="e.g. high_elf, wood_elf, hill_dwarf, mountain_dwarf")
    char_class: str = Field("fighter", description="fighter | rogue | wizard")
    background: str = Field("soldier", description="soldier | criminal | scholar | noble")
    ability_assignment: AbilityAssignment
    skill_choices: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    difficulty: int = Field(3, ge=1, le=5, description="1=Storyteller 2=Adventurer 3=Heroic 4=Tactician 5=Custom")
    custom_rules: Optional[str] = Field(None, description="Narrative rules (used when difficulty=5)")
    character: CharacterCreateRequest


class ActionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=500)


class SaveRequest(BaseModel):
    slot: Optional[str] = Field(None, description="Save slot name; defaults to session_id")


# ── Response Models ────────────────────────────────────────────────────────────

class AbilityScoresOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strength:     int = Field(..., alias="str")
    dex:          int
    con:          int
    intelligence: int = Field(..., alias="int")
    wis:          int
    cha:          int


class CharacterSheet(BaseModel):
    name: str
    race: str
    char_class: str
    level: int
    hp: int
    max_hp: int
    ac: int
    xp: int
    gold: int
    location: str
    ability_scores: AbilityScoresOut
    proficient_skills: list[str]
    proficient_saves: list[str]
    equipped: dict[str, Any]
    inventory: list[Any]
    spell_slots: dict[str, Any]
    known_spells: list[str]
    conditions: list[str]
    death_saves: dict[str, Any]


class NPCSummary(BaseModel):
    kind: str
    hp: int
    max_hp: int
    ac: int
    location: str
    hostile: bool
    alive: bool
    conditions: list[str]


class QuestOut(BaseModel):
    title: str
    description: str
    objectives: list[Any]
    completed: bool


class CombatOut(BaseModel):
    active: bool
    round: int
    current_actor: str
    initiative_order: list[str]


class SessionOut(BaseModel):
    session_id: str
    status: str          # awaiting_character | active | game_over
    difficulty: int
    custom_rules: Optional[str]
    created_at: str
    player_name: Optional[str] = None
    player_level: Optional[int] = None
    in_combat: bool = False


class ActionResponse(BaseModel):
    session_id: str
    intent_type: str
    mechanic_result: str
    dm_response: str
    player_hp: int
    player_max_hp: int
    player_location: str
    in_combat: bool
    combat: Optional[CombatOut]
    events: list[str]


class GameStateResponse(BaseModel):
    session_id: str
    status: str
    scene: str
    player: CharacterSheet
    npcs: dict[str, NPCSummary]
    quests: list[QuestOut]
    turn_history: list[str]
    combat: Optional[CombatOut]


class InventoryOut(BaseModel):
    equipped: dict[str, Any]
    inventory: list[Any]
    gold: int
    spell_slots: dict[str, Any]


class ReferenceData(BaseModel):
    data: dict[str, Any]
