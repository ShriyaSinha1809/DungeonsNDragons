"""Tests for state_manager.py — state tracking and persistence."""
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from src.state_manager import (
    PlayerState, NPCState, AbilityScores, WorldState,
    StateManager, CombatState, QuestState
)
from src.config_builder import SessionConfig


def _make_config(difficulty=3) -> SessionConfig:
    return SessionConfig(difficulty=difficulty)


def _make_player(**kwargs) -> PlayerState:
    defaults = dict(
        name="Testero", char_class="fighter", race="human", level=1,
        hp=10, max_hp=10, ac=15,
        ability_scores=AbilityScores(str=16, dex=12, con=14, int=10, wis=10, cha=10),
        location="Tavern",
        proficient_skills=["athletics", "intimidation"],
        proficient_saves=["str", "con"],
        equipped={"main_hand": "longsword", "armor": "chain_mail"},
        inventory=[{"type": "healing_potion", "qty": 2}],
    )
    defaults.update(kwargs)
    return PlayerState(**defaults)


# ---------------------------------------------------------------------------
# AbilityScores
# ---------------------------------------------------------------------------

class TestAbilityScores:
    def test_defaults_are_ten(self):
        ab = AbilityScores()
        for attr in ("str", "dex", "con", "int", "wis", "cha"):
            assert getattr(ab, attr) == 10

    def test_to_dict_roundtrip(self):
        ab = AbilityScores(str=16, dex=14, con=12, int=10, wis=8, cha=9)
        d = ab.to_dict()
        ab2 = AbilityScores.from_dict(d)
        assert ab.str == ab2.str
        assert ab.dex == ab2.dex

    def test_from_dict_ignores_extra_keys(self):
        d = {"str": 10, "dex": 12, "con": 10, "int": 10, "wis": 10, "cha": 10, "extra": 99}
        ab = AbilityScores.from_dict(d)
        assert ab.dex == 12


# ---------------------------------------------------------------------------
# PlayerState
# ---------------------------------------------------------------------------

class TestPlayerState:
    def test_is_unconscious_when_hp_zero(self):
        p = _make_player(hp=0)
        assert p.is_unconscious()

    def test_not_unconscious_when_hp_positive(self):
        p = _make_player(hp=5)
        assert not p.is_unconscious()

    def test_is_dead_after_three_failures(self):
        p = _make_player(death_saves={"successes": 0, "failures": 3})
        assert p.is_dead()

    def test_not_dead_with_two_failures(self):
        p = _make_player(death_saves={"successes": 0, "failures": 2})
        assert not p.is_dead()

    def test_to_dict_from_dict_roundtrip(self):
        p = _make_player()
        d = p.to_dict()
        p2 = PlayerState.from_dict(d)
        assert p2.name == p.name
        assert p2.char_class == p.char_class
        assert p2.ability_scores.str == p.ability_scores.str
        assert p2.proficient_skills == p.proficient_skills

    def test_to_snapshot_dict_has_required_keys(self):
        p = _make_player()
        snap = p.to_snapshot_dict()
        required = {"name", "level", "ability_scores", "proficient_skills",
                    "proficient_saves", "equipped", "conditions", "char_class",
                    "ac", "hp", "max_hp"}
        assert required.issubset(snap.keys())


# ---------------------------------------------------------------------------
# NPCState
# ---------------------------------------------------------------------------

class TestNPCState:
    def _goblin_yaml(self):
        return {
            "kind": "Goblin",
            "default_ac": 15,
            "max_hp": 7,
            "hp_die": "2d6",
            "speed": 30,
            "ability": {"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
            "skills": {"stealth": 6},
            "cr": 0.25,
            "xp": 50,
            "proficiency_bonus": 2,
            "actions": [{"name": "Scimitar", "type": "melee_attack", "attack": 4,
                          "damage_die": "1d6+2", "damage_type": "slashing", "range": 5}],
            "equipped": ["scimitar"],
            "default_inventory": [{"type": "gold_piece", "qty": 3}],
        }

    def test_from_yaml_creates_correct_hp(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        assert npc.hp == 7
        assert npc.max_hp == 7

    def test_from_yaml_applies_hp_multiplier(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml(), hp_multiplier=2.0)
        assert npc.hp == 14
        assert npc.max_hp == 14

    def test_from_yaml_sets_kind(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        assert npc.kind == "Goblin"

    def test_from_yaml_sets_ability_scores(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        assert npc.ability_scores.dex == 14

    def test_is_alive_when_hp_positive(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        assert npc.is_alive()

    def test_not_alive_when_hp_zero(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        npc.hp = 0
        assert not npc.is_alive()

    def test_to_dict_from_dict_roundtrip(self):
        npc = NPCState.from_yaml("goblin_1", self._goblin_yaml())
        d = npc.to_dict()
        npc2 = NPCState.from_dict(d)
        assert npc2.kind == npc.kind
        assert npc2.hp == npc.hp
        assert npc2.ability_scores.dex == npc.ability_scores.dex


# ---------------------------------------------------------------------------
# CombatState
# ---------------------------------------------------------------------------

class TestCombatState:
    def test_current_actor_id(self):
        cs = CombatState(initiative_order=["player", "goblin_1", "goblin_2"],
                         current_turn_index=0, active=True)
        assert cs.current_actor_id() == "player"

    def test_advance_turn(self):
        cs = CombatState(initiative_order=["player", "goblin_1"],
                         current_turn_index=0, active=True)
        next_actor = cs.advance_turn()
        assert next_actor == "goblin_1"

    def test_advance_skips_dead(self):
        cs = CombatState(initiative_order=["player", "goblin_1", "goblin_2"],
                         current_turn_index=0, active=True)
        next_actor = cs.advance_turn(dead_ids={"goblin_1"})
        assert next_actor == "goblin_2"

    def test_round_increments_at_cycle(self):
        cs = CombatState(initiative_order=["player", "goblin_1"],
                         current_turn_index=1, round_number=1, active=True)
        cs.advance_turn()
        assert cs.round_number == 2

    def test_to_dict_from_dict(self):
        cs = CombatState(initiative_order=["player", "goblin_1"],
                         current_turn_index=0, round_number=2, active=True,
                         combatants={"player": "player", "goblin_1": "npc"})
        d = cs.to_dict()
        cs2 = CombatState.from_dict(d)
        assert cs2.round_number == 2
        assert cs2.initiative_order == ["player", "goblin_1"]


# ---------------------------------------------------------------------------
# StateManager — data loading and spawning
# ---------------------------------------------------------------------------

class TestStateManager:
    def setup_method(self):
        self.config = _make_config()
        self.sm = StateManager(self.config)
        self.sm.load_data_files()

    def test_load_data_files_loads_npcs(self):
        goblin_data = self.sm.get_npc_data("goblin")
        assert goblin_data, "goblin.yaml should be loaded"
        assert "kind" in goblin_data

    def test_load_data_files_loads_weapons(self):
        longsword = self.sm.get_weapon_data("longsword")
        assert longsword, "weapons.yaml should contain longsword"
        assert longsword.get("damage") == "1d8"

    def test_load_data_files_loads_classes(self):
        fighter = self.sm.get_class_data("fighter")
        assert fighter, "fighter.yaml should be loaded"
        assert fighter.get("hit_die_sides") == 10

    def test_spawn_npc_creates_state(self):
        npc = self.sm.spawn_npc("goblin", "g1", "Cave")
        assert npc.npc_id == "g1"
        assert npc.location == "Cave"
        assert npc.hp > 0

    def test_spawn_npc_applies_hp_multiplier_easy(self):
        easy_config = SessionConfig(difficulty=1)
        easy_sm = StateManager(easy_config)
        easy_sm.load_data_files()
        npc = easy_sm.spawn_npc("goblin", "g_easy", "Cave")
        # easy mode: 0.5x HP multiplier → 7 * 0.5 = 3 or 4
        assert npc.max_hp <= 7

    def test_get_hostile_npcs_returns_alive(self):
        self.sm.spawn_npc("goblin", "alive_goblin", "Cave")
        dead_npc = self.sm.spawn_npc("goblin", "dead_goblin", "Cave")
        dead_npc.hp = 0
        hostile = self.sm.world.get_hostile_npcs()
        ids = [n.npc_id for n in hostile]
        assert "alive_goblin" in ids
        assert "dead_goblin" not in ids

    def test_build_context_payload_structure(self):
        self.sm.world.player = _make_player()
        payload = self.sm.build_context_payload()
        assert "player" in payload
        assert "npcs" in payload
        assert "quests" in payload
        assert "history" in payload
        assert "scene" in payload

    def test_award_xp_no_level_up(self):
        self.sm.world.player = _make_player(xp=0)
        leveled = self.sm.award_xp(50)
        assert not leveled
        assert self.sm.world.player.xp == 50

    def test_award_xp_triggers_level_up(self):
        self.sm.world.player = _make_player(xp=0, level=1)
        leveled = self.sm.award_xp(300)  # 300 XP = level 2
        assert leveled
        assert self.sm.world.player.level == 2


# ---------------------------------------------------------------------------
# Save / Load roundtrip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_and_load_roundtrip(self):
        config = _make_config()
        sm = StateManager(config)
        sm.load_data_files()
        sm.world.player = _make_player(name="SavedHero", xp=150, gold=25)
        sm.spawn_npc("goblin", "g1", "Cave")
        sm.setup_default_quest()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            sm.save_game(path)

            sm2 = StateManager(config)
            sm2.load_game(path)

            assert sm2.world.player.name == "SavedHero"
            assert sm2.world.player.xp == 150
            assert sm2.world.player.gold == 25
            assert "g1" in sm2.world.npcs
            assert len(sm2.world.active_quests) == 1
        finally:
            os.unlink(path)

    def test_load_preserves_npc_hp(self):
        config = _make_config()
        sm = StateManager(config)
        sm.load_data_files()
        sm.world.player = _make_player()
        npc = sm.spawn_npc("goblin", "g1", "Cave")
        npc.hp = 3  # damaged goblin

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            sm.save_game(path)
            sm2 = StateManager(config)
            sm2.load_game(path)
            assert sm2.world.npcs["g1"].hp == 3
        finally:
            os.unlink(path)
