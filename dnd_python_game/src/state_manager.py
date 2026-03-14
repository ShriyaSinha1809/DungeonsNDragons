"""
state_manager.py - World state management for the D&D game.
Tracks player, NPCs, quests, combat state, and handles save/load.
"""
import json
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import yaml

from .config_builder import SessionConfig


# ---------------------------------------------------------------------------
# Ability Scores
# ---------------------------------------------------------------------------

@dataclass
class AbilityScores:
    str: int = 10
    dex: int = 10
    con: int = 10
    int: int = 10
    wis: int = 10
    cha: int = 10

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AbilityScores":
        return cls(**{k: v for k, v in data.items() if k in ("str", "dex", "con", "int", "wis", "cha")})


# ---------------------------------------------------------------------------
# Player State
# ---------------------------------------------------------------------------

class PlayerState:
    def __init__(
        self,
        name: str = "Hero",
        char_class: str = "Fighter",
        race: str = "Human",
        level: int = 1,
        hp: int = 10,
        max_hp: int = 10,
        ac: int = 10,
        ability_scores: Optional[AbilityScores] = None,
        location: str = "Tavern",
        proficient_skills: Optional[list] = None,
        proficient_saves: Optional[list] = None,
        equipped: Optional[dict] = None,
        inventory: Optional[list] = None,
        spell_slots: Optional[dict] = None,
        known_spells: Optional[list] = None,
        death_saves: Optional[dict] = None,
        conditions: Optional[list] = None,
        xp: int = 0,
        gold: int = 10,
    ):
        self.name = name
        self.char_class = char_class
        self.race = race
        self.level = level
        self.hp = hp
        self.max_hp = max_hp
        self.ac = ac
        self.ability_scores = ability_scores or AbilityScores()
        self.location = location
        self.proficient_skills = proficient_skills or []
        self.proficient_saves = proficient_saves or []
        self.equipped = equipped or {}
        self.inventory = inventory or []
        self.spell_slots = spell_slots or {}
        self.known_spells = known_spells or []
        self.death_saves = death_saves or {"successes": 0, "failures": 0}
        self.conditions = conditions or []
        self.xp = xp
        self.gold = gold

    def is_unconscious(self) -> bool:
        return self.hp <= 0

    def is_dead(self) -> bool:
        return self.death_saves.get("failures", 0) >= 3

    def is_stable(self) -> bool:
        return self.death_saves.get("successes", 0) >= 3

    def to_snapshot_dict(self) -> dict:
        """Returns a flat dict for MechanicsEngine EntitySnapshot construction."""
        return {
            "name": self.name,
            "level": self.level,
            "ability_scores": self.ability_scores.to_dict(),
            "proficient_skills": self.proficient_skills,
            "proficient_saves": self.proficient_saves,
            "equipped": self.equipped,
            "conditions": self.conditions,
            "char_class": self.char_class,
            "ac": self.ac,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "spell_slots": self.spell_slots,
            "known_spells": self.known_spells,
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "char_class": self.char_class,
            "race": self.race,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "ac": self.ac,
            "ability_scores": self.ability_scores.to_dict(),
            "location": self.location,
            "proficient_skills": self.proficient_skills,
            "proficient_saves": self.proficient_saves,
            "equipped": self.equipped,
            "inventory": self.inventory,
            "spell_slots": self.spell_slots,
            "known_spells": self.known_spells,
            "death_saves": self.death_saves,
            "conditions": self.conditions,
            "xp": self.xp,
            "gold": self.gold,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerState":
        ability_scores = AbilityScores.from_dict(data.get("ability_scores", {}))
        return cls(
            name=data.get("name", "Hero"),
            char_class=data.get("char_class", "Fighter"),
            race=data.get("race", "Human"),
            level=data.get("level", 1),
            hp=data.get("hp", 10),
            max_hp=data.get("max_hp", 10),
            ac=data.get("ac", 10),
            ability_scores=ability_scores,
            location=data.get("location", "Tavern"),
            proficient_skills=data.get("proficient_skills", []),
            proficient_saves=data.get("proficient_saves", []),
            equipped=data.get("equipped", {}),
            inventory=data.get("inventory", []),
            spell_slots=data.get("spell_slots", {}),
            known_spells=data.get("known_spells", []),
            death_saves=data.get("death_saves", {"successes": 0, "failures": 0}),
            conditions=data.get("conditions", []),
            xp=data.get("xp", 0),
            gold=data.get("gold", 10),
        )


# ---------------------------------------------------------------------------
# NPC State
# ---------------------------------------------------------------------------

class NPCState:
    def __init__(
        self,
        npc_id: str,
        kind: str,
        hp: int,
        max_hp: int,
        ac: int,
        ability_scores: Optional[AbilityScores] = None,
        location: str = "unknown",
        hostile: bool = True,
        equipped: Optional[list] = None,
        inventory: Optional[list] = None,
        actions: Optional[list] = None,
        conditions: Optional[list] = None,
        xp_value: int = 0,
        damage_vulnerabilities: Optional[list] = None,
        damage_immunities: Optional[list] = None,
        proficiency_bonus: int = 2,
        skills: Optional[dict] = None,
    ):
        self.npc_id = npc_id
        self.kind = kind
        self.hp = hp
        self.max_hp = max_hp
        self.ac = ac
        self.ability_scores = ability_scores or AbilityScores()
        self.location = location
        self.hostile = hostile
        self.equipped = equipped or []
        self.inventory = inventory or []
        self.actions = actions or []
        self.conditions = conditions or []
        self.xp_value = xp_value
        self.damage_vulnerabilities = damage_vulnerabilities or []
        self.damage_immunities = damage_immunities or []
        self.proficiency_bonus = proficiency_bonus
        self.skills = skills or {}

    def is_alive(self) -> bool:
        return self.hp > 0

    def to_snapshot_dict(self) -> dict:
        return {
            "name": f"{self.kind} ({self.npc_id})",
            "level": max(1, self.proficiency_bonus - 1),  # approximate
            "ability_scores": self.ability_scores.to_dict(),
            "proficient_skills": list(self.skills.keys()),
            "proficient_saves": [],
            "equipped": {"main_hand": self.equipped[0] if self.equipped else "unarmed"},
            "conditions": self.conditions,
            "char_class": "npc",
            "ac": self.ac,
            "hp": self.hp,
            "max_hp": self.max_hp,
        }

    def to_dict(self) -> dict:
        return {
            "npc_id": self.npc_id,
            "kind": self.kind,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "ac": self.ac,
            "ability_scores": self.ability_scores.to_dict(),
            "location": self.location,
            "hostile": self.hostile,
            "equipped": self.equipped,
            "inventory": self.inventory,
            "actions": self.actions,
            "conditions": self.conditions,
            "xp_value": self.xp_value,
            "damage_vulnerabilities": self.damage_vulnerabilities,
            "damage_immunities": self.damage_immunities,
            "proficiency_bonus": self.proficiency_bonus,
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NPCState":
        ability_scores = AbilityScores.from_dict(data.get("ability_scores", {}))
        return cls(
            npc_id=data["npc_id"],
            kind=data["kind"],
            hp=data["hp"],
            max_hp=data["max_hp"],
            ac=data["ac"],
            ability_scores=ability_scores,
            location=data.get("location", "unknown"),
            hostile=data.get("hostile", True),
            equipped=data.get("equipped", []),
            inventory=data.get("inventory", []),
            actions=data.get("actions", []),
            conditions=data.get("conditions", []),
            xp_value=data.get("xp_value", 0),
            damage_vulnerabilities=data.get("damage_vulnerabilities", []),
            damage_immunities=data.get("damage_immunities", []),
            proficiency_bonus=data.get("proficiency_bonus", 2),
            skills=data.get("skills", {}),
        )

    @classmethod
    def from_yaml(cls, npc_id: str, yaml_data: dict, hp_multiplier: float = 1.0) -> "NPCState":
        ability_data = yaml_data.get("ability", {})
        ability_scores = AbilityScores(
            str=ability_data.get("str", 10),
            dex=ability_data.get("dex", 10),
            con=ability_data.get("con", 10),
            int=ability_data.get("int", 10),
            wis=ability_data.get("wis", 8),
            cha=ability_data.get("cha", 8),
        )
        base_hp = yaml_data.get("max_hp", 7)
        adjusted_hp = max(1, int(base_hp * hp_multiplier))

        return cls(
            npc_id=npc_id,
            kind=yaml_data.get("kind", "Unknown"),
            hp=adjusted_hp,
            max_hp=adjusted_hp,
            ac=yaml_data.get("default_ac", 12),
            ability_scores=ability_scores,
            location="unknown",
            hostile=True,
            equipped=yaml_data.get("equipped", []),
            inventory=yaml_data.get("default_inventory", []),
            actions=yaml_data.get("actions", []),
            conditions=[],
            xp_value=yaml_data.get("xp", 0),
            damage_vulnerabilities=yaml_data.get("damage_vulnerabilities", []),
            damage_immunities=yaml_data.get("damage_immunities", []),
            proficiency_bonus=yaml_data.get("proficiency_bonus", 2),
            skills=yaml_data.get("skills", {}),
        )


# ---------------------------------------------------------------------------
# Combat State
# ---------------------------------------------------------------------------

@dataclass
class CombatState:
    initiative_order: list[str] = field(default_factory=list)  # entity IDs in order
    current_turn_index: int = 0
    round_number: int = 1
    active: bool = True
    combatants: dict = field(default_factory=dict)  # id → "player" | "npc"

    def current_actor_id(self) -> str:
        if not self.initiative_order:
            return ""
        return self.initiative_order[self.current_turn_index % len(self.initiative_order)]

    def advance_turn(self, dead_ids: set = None) -> str:
        dead_ids = dead_ids or set()
        for _ in range(len(self.initiative_order)):
            self.current_turn_index = (self.current_turn_index + 1) % len(self.initiative_order)
            if self.current_turn_index == 0:
                self.round_number += 1
            actor = self.initiative_order[self.current_turn_index]
            if actor not in dead_ids:
                return actor
        return self.initiative_order[self.current_turn_index]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CombatState":
        return cls(**data)


# ---------------------------------------------------------------------------
# Quest State
# ---------------------------------------------------------------------------

@dataclass
class QuestState:
    quest_id: str
    title: str
    description: str
    objectives: list[dict] = field(default_factory=list)
    completed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QuestState":
        return cls(**data)


# ---------------------------------------------------------------------------
# World State
# ---------------------------------------------------------------------------

class WorldState:
    def __init__(self, config: SessionConfig):
        self.config = config
        self.player: Optional[PlayerState] = None
        self.npcs: dict[str, NPCState] = {}
        self.active_quests: list[QuestState] = []
        self.turn_history: list[str] = []
        self.current_scene: str = "You find yourself in a dimly lit tavern at the edge of town."
        self.combat_state: Optional[CombatState] = None

    def log_action(self, action: str, result: str):
        entry = f"Player: '{action}' → {result}"
        self.turn_history.append(entry)
        if len(self.turn_history) > 20:
            self.turn_history = self.turn_history[-20:]

    def update_location(self, new_location: str):
        if self.player:
            self.player.location = new_location

    def add_npc(self, npc: NPCState):
        self.npcs[npc.npc_id] = npc

    def remove_npc(self, npc_id: str):
        self.npcs.pop(npc_id, None)

    def get_hostile_npcs(self) -> list[NPCState]:
        return [npc for npc in self.npcs.values() if npc.hostile and npc.is_alive()]

    def get_alive_npcs(self) -> list[NPCState]:
        return [npc for npc in self.npcs.values() if npc.is_alive()]


# ---------------------------------------------------------------------------
# State Manager
# ---------------------------------------------------------------------------

class StateManager:
    def __init__(self, config: SessionConfig):
        self.world = WorldState(config)
        self._data_cache: dict[str, Any] = {}
        # Data directory relative to this file
        self._data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

    def load_data_files(self):
        """Load all YAML data files into memory cache."""
        categories = {
            "npcs": os.path.join(self._data_dir, "npcs"),
            "items_weapons": os.path.join(self._data_dir, "items", "weapons.yaml"),
            "items_armor": os.path.join(self._data_dir, "items", "armor.yaml"),
            "items_spells": os.path.join(self._data_dir, "items", "spells.yaml"),
        }

        # Load NPC files
        self._data_cache["npcs"] = {}
        npc_dir = categories["npcs"]
        if os.path.isdir(npc_dir):
            for fname in os.listdir(npc_dir):
                if fname.endswith(".yaml"):
                    with open(os.path.join(npc_dir, fname)) as f:
                        data = yaml.safe_load(f)
                        key = fname.replace(".yaml", "")
                        self._data_cache["npcs"][key] = data

        # Load flat YAML files
        for key in ("items_weapons", "items_armor", "items_spells"):
            path = categories[key]
            if os.path.isfile(path):
                with open(path) as f:
                    self._data_cache[key] = yaml.safe_load(f) or {}

        # Load char classes
        self._data_cache["classes"] = {}
        classes_dir = os.path.join(self._data_dir, "char_classes")
        if os.path.isdir(classes_dir):
            for fname in os.listdir(classes_dir):
                if fname.endswith(".yaml"):
                    with open(os.path.join(classes_dir, fname)) as f:
                        key = fname.replace(".yaml", "")
                        self._data_cache["classes"][key] = yaml.safe_load(f)

        # Load races
        self._data_cache["races"] = {}
        races_dir = os.path.join(self._data_dir, "races")
        if os.path.isdir(races_dir):
            for fname in os.listdir(races_dir):
                if fname.endswith(".yaml"):
                    with open(os.path.join(races_dir, fname)) as f:
                        key = fname.replace(".yaml", "")
                        self._data_cache["races"][key] = yaml.safe_load(f)

    def get_npc_data(self, kind: str) -> dict:
        return self._data_cache.get("npcs", {}).get(kind.lower(), {})

    def get_weapon_data(self, weapon_name: str) -> dict:
        return self._data_cache.get("items_weapons", {}).get(weapon_name.lower().replace(" ", "_"), {})

    def get_armor_data(self, armor_name: str) -> dict:
        return self._data_cache.get("items_armor", {}).get(armor_name.lower().replace(" ", "_"), {})

    def get_spell_data(self, spell_name: str) -> dict:
        key = spell_name.lower().replace(" ", "_")
        return self._data_cache.get("items_spells", {}).get(key, {})

    def get_class_data(self, class_name: str) -> dict:
        return self._data_cache.get("classes", {}).get(class_name.lower(), {})

    def get_race_data(self, race_name: str) -> dict:
        return self._data_cache.get("races", {}).get(race_name.lower(), {})

    def spawn_npc(self, kind: str, npc_id: str = None, location: str = "unknown") -> NPCState:
        """Create an NPCState from YAML data and add to world."""
        yaml_data = self.get_npc_data(kind)
        if not yaml_data:
            # Fallback minimal NPC
            yaml_data = {"kind": kind.title(), "max_hp": 10, "default_ac": 12,
                        "ability": {}, "actions": [], "xp": 25}

        hp_multiplier = self.world.config.modifiers.get("enemy_hp_multiplier", 1.0)
        if npc_id is None:
            existing = sum(1 for k in self.world.npcs if k.startswith(kind.lower()))
            npc_id = f"{kind.lower()}_{existing + 1}"

        npc = NPCState.from_yaml(npc_id, yaml_data, hp_multiplier)
        npc.location = location
        self.world.add_npc(npc)
        return npc

    def setup_default_quest(self):
        """Add the default goblin cave quest."""
        quest = QuestState(
            quest_id="goblin_cave",
            title="Clear the Goblin Cave",
            description="A group of goblins has been terrorizing the local village. Clear them out!",
            objectives=[
                {"description": "Defeat all goblins in the cave", "completed": False},
                {"description": "Return to the village elder", "completed": False},
            ]
        )
        self.world.active_quests.append(quest)

    def resolve_mechanic(self, action: str, parsed_intent: dict) -> str:
        """Route mechanic resolution based on parsed intent type."""
        from .mechanics import MechanicsEngine, EntitySnapshot

        engine = MechanicsEngine()

        if not self.world.player:
            return "Action requires narrative resolution."

        player = self.world.player
        snapshot = EntitySnapshot(**player.to_snapshot_dict())

        intent_type = parsed_intent.get("type", "narrative")
        skill = parsed_intent.get("skill", "")

        config_mods = self.world.config.modifiers
        adv = config_mods.get("player_advantage", False)
        disadv = config_mods.get("player_disadvantage", False)

        skill_map = {
            "stealth": ("stealth", 12),
            "perception": ("perception", 13),
            "athletics": ("athletics", 14),
            "persuasion": ("persuasion", 15),
            "deception": ("deception", 14),
            "intimidation": ("intimidation", 13),
            "investigation": ("investigation", 13),
            "thieves_tools": ("thieves_tools", 15),
            "insight": ("insight", 12),
            "survival": ("survival", 12),
        }

        if intent_type == "skill_check" and skill in skill_map:
            skill_name, default_dc = skill_map[skill]
            result = engine.resolve_skill_check(snapshot, skill_name, default_dc,
                                                advantage=adv, disadvantage=disadv)
            self.world.log_action(action, result.mechanical_summary())
            return result.mechanical_summary()

        return "Action requires narrative resolution."

    def build_context_payload(self) -> dict:
        """Build comprehensive context dict for the DM Agent."""
        player = self.world.player
        player_data = player.to_dict() if player else {}

        npc_summaries = {}
        for npc_id, npc in self.world.npcs.items():
            npc_summaries[npc_id] = {
                "kind": npc.kind,
                "hp": npc.hp,
                "max_hp": npc.max_hp,
                "ac": npc.ac,
                "location": npc.location,
                "hostile": npc.hostile,
                "alive": npc.is_alive(),
                "conditions": npc.conditions,
            }

        quest_summaries = []
        for q in self.world.active_quests:
            quest_summaries.append({
                "title": q.title,
                "description": q.description,
                "objectives": q.objectives,
                "completed": q.completed,
            })

        combat_summary = None
        if self.world.combat_state and self.world.combat_state.active:
            cs = self.world.combat_state
            combat_summary = {
                "active": True,
                "round": cs.round_number,
                "current_actor": cs.current_actor_id(),
                "initiative_order": cs.initiative_order,
            }

        return {
            "player": player_data,
            "npcs": npc_summaries,
            "quests": quest_summaries,
            "history": self.world.turn_history[-5:],
            "scene": self.world.current_scene,
            "combat": combat_summary,
            "difficulty_rules": (
                self.world.config.custom_rules
                if self.world.config.custom_rules
                else f"Difficulty Modifiers: {self.world.config.modifiers}"
            ),
        }

    def award_xp(self, amount: int) -> bool:
        """Award XP and return True if the player leveled up."""
        from .mechanics import MechanicsEngine
        if not self.world.player:
            return False

        engine = MechanicsEngine()
        old_level = self.world.player.level
        self.world.player.xp += amount
        new_level = engine.level_from_xp(self.world.player.xp)

        if new_level > old_level:
            self.world.player.level = new_level
            # Increase max HP: roll hit die + CON mod
            class_data = self.get_class_data(self.world.player.char_class)
            hit_die_sides = class_data.get("hit_die_sides", 8)
            con_mod = engine.ability_modifier(self.world.player.ability_scores.con)
            hp_gain = max(1, random.randint(1, hit_die_sides) + con_mod)
            self.world.player.max_hp += hp_gain
            self.world.player.hp = min(self.world.player.hp + hp_gain, self.world.player.max_hp)
            return True
        return False

    def save_game(self, filepath: str):
        """Serialize full WorldState to JSON."""
        data = {
            "player": self.world.player.to_dict() if self.world.player else None,
            "npcs": {npc_id: npc.to_dict() for npc_id, npc in self.world.npcs.items()},
            "active_quests": [q.to_dict() for q in self.world.active_quests],
            "turn_history": self.world.turn_history,
            "current_scene": self.world.current_scene,
            "combat_state": self.world.combat_state.to_dict() if self.world.combat_state else None,
            "config": {
                "difficulty": self.world.config.difficulty,
                "custom_rules": self.world.config.custom_rules,
            },
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def load_game(self, filepath: str):
        """Deserialize WorldState from JSON."""
        with open(filepath) as f:
            data = json.load(f)

        if data.get("player"):
            self.world.player = PlayerState.from_dict(data["player"])

        self.world.npcs = {}
        for npc_id, npc_data in data.get("npcs", {}).items():
            self.world.npcs[npc_id] = NPCState.from_dict(npc_data)

        self.world.active_quests = [
            QuestState.from_dict(q) for q in data.get("active_quests", [])
        ]
        self.world.turn_history = data.get("turn_history", [])
        self.world.current_scene = data.get("current_scene", "")

        if data.get("combat_state"):
            self.world.combat_state = CombatState.from_dict(data["combat_state"])
