"""
character_service.py — JSON-driven character creation.
Replicates CharacterBuilder logic without any Rich prompts or interactivity.
"""
from src.state_manager import PlayerState, AbilityScores
from src.mechanics import MechanicsEngine
from .models import CharacterCreateRequest

# ── Background definitions ─────────────────────────────────────────────────────

BACKGROUNDS: dict[str, dict] = {
    "soldier":  {"skills": ["athletics", "intimidation"], "gold": 10},
    "criminal": {"skills": ["stealth", "deception"],      "gold": 15},
    "scholar":  {"skills": ["arcana", "history"],         "gold": 10},
    "noble":    {"skills": ["history", "persuasion"],     "gold": 25},
}

_engine = MechanicsEngine()


# ── Public API ─────────────────────────────────────────────────────────────────

def build_player(req: CharacterCreateRequest, state_manager) -> PlayerState:
    """
    Construct a fully initialised PlayerState from a CharacterCreateRequest.

    Args:
        req:           Validated Pydantic request model.
        state_manager: A loaded StateManager (for YAML data lookup).

    Returns:
        A PlayerState ready to assign to WorldState.player.

    Raises:
        ValueError: if race or class keys are not found in data files.
    """
    race_key  = req.race.lower()
    class_key = req.char_class.lower()
    bg_key    = req.background.lower()

    race_data  = state_manager.get_race_data(race_key)
    class_data = state_manager.get_class_data(class_key)
    bg_data    = BACKGROUNDS.get(bg_key, BACKGROUNDS["soldier"])

    if not race_data:
        raise ValueError(f"Unknown race '{req.race}'. Valid: human, elf, halfling, dwarf.")
    if not class_data:
        raise ValueError(f"Unknown class '{req.char_class}'. Valid: fighter, rogue, wizard.")

    # ── Ability scores ─────────────────────────────────────────────────────────
    ab = req.ability_assignment
    scores = {
        "str": ab.strength, "dex": ab.dex, "con": ab.con,
        "int": ab.intelligence, "wis": ab.wis, "cha": ab.cha,
    }

    # Apply base racial bonuses
    for stat, bonus in race_data.get("attribute_bonus", {}).items():
        scores[stat] = scores.get(stat, 10) + bonus

    # Apply subrace bonuses
    if req.subrace:
        subraces = race_data.get("subrace", {})
        sr_data = subraces.get(req.subrace.lower(), {})
        for stat, bonus in sr_data.get("attribute_bonus", {}).items():
            scores[stat] = scores.get(stat, 10) + bonus

    ability_scores = AbilityScores(**scores)
    con_mod = _engine.ability_modifier(ability_scores.con)
    dex_mod = _engine.ability_modifier(ability_scores.dex)

    # ── HP & AC ────────────────────────────────────────────────────────────────
    hit_die_sides = class_data.get("hit_die_sides", 8)
    max_hp = max(1, hit_die_sides + con_mod)

    equipped, inventory = _assign_equipment(class_data.get("starting_equipment", []))
    inventory.append({"type": "healing_potion", "qty": 1})
    ac = _calculate_ac(equipped, dex_mod, state_manager)

    # ── Skills ─────────────────────────────────────────────────────────────────
    all_skills = list(bg_data["skills"])
    class_skill_pool = class_data.get("available_skills", [])
    num_extra = class_data.get("available_skills_choices", 2)
    valid_extra = [s for s in req.skill_choices
                   if s in class_skill_pool and s not in all_skills]
    all_skills.extend(valid_extra[:num_extra])

    # ── Saving throws ──────────────────────────────────────────────────────────
    proficient_saves = class_data.get("saving_throw_proficiency", [])

    # ── Spells (wizard only) ───────────────────────────────────────────────────
    known_spells: list[str] = []
    spell_slots: dict[str, int] = {}
    if class_key == "wizard":
        cantrips = class_data.get("default_cantrips", ["firebolt", "ray_of_frost", "shocking_grasp"])
        spells   = class_data.get("default_spells", ["magic_missile", "mage_armor"])
        known_spells = spells + cantrips
        slots_by_level = class_data.get("spell_slots_by_level", {})
        # slots_by_level[character_level][spell_level]
        lvl1_slots = (
            slots_by_level.get(1, {}).get(1, 2)
            if isinstance(slots_by_level, dict)
            else 2
        )
        spell_slots = {"1": lvl1_slots}

    return PlayerState(
        name=req.name,
        char_class=class_key,
        race=race_key,
        level=1,
        hp=max_hp,
        max_hp=max_hp,
        ac=ac,
        ability_scores=ability_scores,
        location="Tavern — The Tipsy Flagon",
        proficient_skills=all_skills,
        proficient_saves=proficient_saves,
        equipped=equipped,
        inventory=inventory,
        spell_slots=spell_slots,
        known_spells=known_spells,
        gold=bg_data["gold"],
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

_ARMOR_KEYS = {
    "chain_mail", "leather_armor", "scale_mail", "chain_shirt",
    "padded", "studded_leather", "plate_armor", "hide_armor",
}
_UTILITY_KEYS = {"thieves_tools", "component_pouch", "arcane_focus"}


def _assign_equipment(starting: list[str]) -> tuple[dict, list]:
    equipped: dict = {}
    inventory: list = []
    main_hand_set = off_hand_set = False

    for item in starting:
        key = item.lower()
        if key in _ARMOR_KEYS:
            equipped["armor"] = key
        elif key == "shield":
            equipped["off_hand"] = key
            off_hand_set = True
        elif key in _UTILITY_KEYS:
            equipped["utility"] = key
        elif not main_hand_set:
            equipped["main_hand"] = key
            main_hand_set = True
        elif not off_hand_set:
            inventory.append({"type": key, "qty": 1})
        else:
            inventory.append({"type": key, "qty": 1})

    return equipped, inventory


def _calculate_ac(equipped: dict, dex_mod: int, sm) -> int:
    armor_key = equipped.get("armor", "")
    has_shield = equipped.get("off_hand", "") == "shield"

    if not armor_key:
        base_ac = 10 + dex_mod
    else:
        armor_data = sm.get_armor_data(armor_key)
        base_ac    = armor_data.get("ac", 10)
        mod_cap    = armor_data.get("dex_mod_cap")
        if mod_cap is None:
            base_ac += dex_mod
        elif mod_cap > 0:
            base_ac += min(dex_mod, mod_cap)
        # mod_cap == 0 → heavy armor, no dex bonus

    return base_ac + (2 if has_shield else 0)
