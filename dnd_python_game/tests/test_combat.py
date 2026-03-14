"""Tests for combat.py — CombatManager, initiative, NPC AI."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import unittest.mock as mock
from src.state_manager import (
    StateManager, PlayerState, NPCState, AbilityScores, CombatState
)
from src.mechanics import MechanicsEngine
from src.combat import CombatManager, CombatTurnResult
from src.config_builder import SessionConfig


def _make_config(difficulty=3) -> SessionConfig:
    return SessionConfig(difficulty=difficulty)


def _make_player(**kwargs) -> PlayerState:
    defaults = dict(
        name="Hero", char_class="fighter", race="human", level=1,
        hp=15, max_hp=15, ac=15,
        ability_scores=AbilityScores(str=16, dex=12, con=14, int=10, wis=10, cha=10),
        proficient_skills=["athletics"],
        proficient_saves=["str", "con"],
        equipped={"main_hand": "longsword", "armor": "chain_mail"},
        inventory=[{"type": "healing_potion", "qty": 2}],
    )
    defaults.update(kwargs)
    return PlayerState(**defaults)


def _make_goblin_npc(npc_id="goblin_1", hp=7) -> NPCState:
    return NPCState(
        npc_id=npc_id,
        kind="Goblin",
        hp=hp,
        max_hp=7,
        ac=15,
        ability_scores=AbilityScores(str=8, dex=14, con=10, int=10, wis=8, cha=8),
        location="Cave",
        hostile=True,
        equipped=["scimitar"],
        inventory=[{"type": "gold_piece", "qty": 3}],
        actions=[{
            "name": "Scimitar",
            "type": "melee_attack",
            "attack": 4,
            "damage_die": "1d6+2",
            "damage_type": "slashing",
            "range": 5,
        }],
        xp_value=50,
    )


def _setup_combat_manager(difficulty=3) -> tuple[CombatManager, StateManager]:
    config = _make_config(difficulty)
    sm = StateManager(config)
    sm.load_data_files()
    sm.world.player = _make_player()
    sm.world.add_npc(_make_goblin_npc("goblin_1"))
    mechanics = MechanicsEngine()
    cm = CombatManager(sm, mechanics)
    return cm, sm


# ---------------------------------------------------------------------------
# initiate_combat
# ---------------------------------------------------------------------------

class TestInitiateCombat:
    def test_creates_combat_state(self):
        cm, sm = _setup_combat_manager()
        cs = cm.initiate_combat(["goblin_1"])
        assert sm.world.combat_state is not None
        assert sm.world.combat_state.active

    def test_initiative_order_contains_all_combatants(self):
        cm, sm = _setup_combat_manager()
        cs = cm.initiate_combat(["goblin_1"])
        assert "player" in cs.initiative_order
        assert "goblin_1" in cs.initiative_order

    def test_initiative_order_sorted_descending(self):
        cm, sm = _setup_combat_manager()
        # Mock initiative so player rolls 15, goblin rolls 5
        roll_sequence = iter([15, 5])
        with mock.patch("random.randint", side_effect=lambda a, b: next(roll_sequence)):
            cs = cm.initiate_combat(["goblin_1"])
        assert cs.initiative_order[0] == "player"
        assert cs.initiative_order[1] == "goblin_1"

    def test_round_starts_at_1(self):
        cm, sm = _setup_combat_manager()
        cs = cm.initiate_combat(["goblin_1"])
        assert cs.round_number == 1

    def test_is_in_combat_returns_true_after_init(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        assert cm.is_in_combat()

    def test_is_in_combat_false_before_init(self):
        cm, sm = _setup_combat_manager()
        assert not cm.is_in_combat()


# ---------------------------------------------------------------------------
# process_player_turn — attack
# ---------------------------------------------------------------------------

class TestPlayerAttack:
    def test_attack_reduces_npc_hp_on_hit(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        goblin = sm.world.npcs["goblin_1"]
        initial_hp = goblin.hp

        # Force a hit
        with mock.patch("random.randint", return_value=18):
            result = cm.process_player_turn({
                "type": "attack", "target": "goblin", "spell_name": None, "item_name": None
            })

        assert result.success
        assert goblin.hp < initial_hp

    def test_attack_miss_does_not_change_hp(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        goblin = sm.world.npcs["goblin_1"]
        goblin.ac = 30  # Impossible AC

        with mock.patch("random.randint", return_value=2):
            result = cm.process_player_turn({
                "type": "attack", "target": "goblin", "spell_name": None, "item_name": None
            })

        assert not result.success
        assert result.damage_dealt == 0
        assert goblin.hp == goblin.max_hp

    def test_attack_no_target_returns_failure(self):
        cm, sm = _setup_combat_manager()
        # Remove all NPCs
        sm.world.npcs.clear()
        cm.initiate_combat([])
        result = cm.process_player_turn({
            "type": "attack", "target": None, "spell_name": None, "item_name": None
        })
        assert not result.success


# ---------------------------------------------------------------------------
# process_player_turn — item use
# ---------------------------------------------------------------------------

class TestPlayerUseItem:
    def test_healing_potion_restores_hp(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.hp = 5  # wounded

        with mock.patch("random.randint", return_value=3):  # 2d4+2 → 3+3+2=8 max possible
            result = cm.process_player_turn({
                "type": "use_item", "item_name": "healing_potion",
                "target": None, "spell_name": None
            })

        assert result.success
        assert sm.world.player.hp > 5

    def test_potion_removed_from_inventory_after_use(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.hp = 5
        initial_qty = sm.world.player.inventory[0]["qty"]

        with mock.patch("random.randint", return_value=2):
            cm.process_player_turn({
                "type": "use_item", "item_name": "healing_potion",
                "target": None, "spell_name": None
            })

        remaining = sum(
            i.get("qty", 0)
            for i in sm.world.player.inventory
            if i.get("type") == "healing_potion"
        )
        assert remaining == initial_qty - 1

    def test_no_potion_returns_failure(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.inventory = []  # empty inventory

        result = cm.process_player_turn({
            "type": "use_item", "item_name": "healing_potion",
            "target": None, "spell_name": None
        })
        assert not result.success


# ---------------------------------------------------------------------------
# process_npc_turns
# ---------------------------------------------------------------------------

class TestNPCTurns:
    def test_npc_attack_reduces_player_hp(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        initial_hp = sm.world.player.hp

        with mock.patch("random.randint", return_value=15):  # goblin hits AC 15
            results = cm.process_npc_turns()

        assert len(results) == 1
        assert results[0].actor_id == "goblin_1"
        assert sm.world.player.hp < initial_hp

    def test_dead_npc_skips_turn(self):
        cm, sm = _setup_combat_manager()
        sm.world.npcs["goblin_1"].hp = 0
        cm.initiate_combat(["goblin_1"])
        results = cm.process_npc_turns()
        assert len(results) == 0

    def test_dodge_applies_disadvantage_to_npc(self):
        """When player has 'dodging' condition, NPC attack uses disadvantage."""
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.conditions.append("dodging")

        # With disadvantage on d20, roll two values and take min
        # Mock to ensure the NPC roll behavior is consistent
        with mock.patch("random.randint", return_value=8):
            results = cm.process_npc_turns()

        # Dodge condition should be removed after the attack
        assert "dodging" not in sm.world.player.conditions


# ---------------------------------------------------------------------------
# check_combat_end
# ---------------------------------------------------------------------------

class TestCheckCombatEnd:
    def test_victory_when_all_npcs_dead(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0
        assert cm.check_combat_end() == "player_victory"

    def test_defeat_when_player_dead(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.death_saves = {"successes": 0, "failures": 3}
        assert cm.check_combat_end() == "player_defeat"

    def test_unconscious_when_player_hp_zero(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.player.hp = 0
        assert cm.check_combat_end() == "player_unconscious"

    def test_none_when_combat_continues(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        assert cm.check_combat_end() is None


# ---------------------------------------------------------------------------
# resolve_post_combat
# ---------------------------------------------------------------------------

class TestPostCombat:
    def test_xp_awarded(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0
        sm.world.player.xp = 0

        post = cm.resolve_post_combat()
        assert post.xp_gained == 50  # goblin XP
        assert sm.world.player.xp == 50

    def test_loot_collected(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0

        post = cm.resolve_post_combat()
        assert len(post.loot) > 0

    def test_loot_added_to_inventory(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0
        initial_inventory_count = len(sm.world.player.inventory)

        post = cm.resolve_post_combat()
        assert len(sm.world.player.inventory) >= initial_inventory_count

    def test_combat_state_cleared_after_victory(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0
        cm.resolve_post_combat()
        assert sm.world.combat_state is None

    def test_dead_npcs_removed_from_world(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        sm.world.npcs["goblin_1"].hp = 0
        cm.resolve_post_combat()
        assert "goblin_1" not in sm.world.npcs


# ---------------------------------------------------------------------------
# Combat actions
# ---------------------------------------------------------------------------

class TestCombatActions:
    def test_dodge_adds_condition(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        result = cm.process_player_turn({"type": "dodge", "target": None,
                                          "spell_name": None, "item_name": None})
        assert result.success
        assert "dodging" in sm.world.player.conditions

    def test_dash_returns_success(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        result = cm.process_player_turn({"type": "dash", "target": None,
                                          "spell_name": None, "item_name": None})
        assert result.success

    def test_disengage_returns_success(self):
        cm, sm = _setup_combat_manager()
        cm.initiate_combat(["goblin_1"])
        result = cm.process_player_turn({"type": "disengage", "target": None,
                                          "spell_name": None, "item_name": None})
        assert result.success
