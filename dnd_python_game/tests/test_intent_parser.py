"""Tests for intent_parser.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from src.intent_parser import IntentParser


@pytest.fixture
def parser():
    return IntentParser()


class TestAttackParsing:
    def test_attack_basic(self, parser):
        result = parser.parse("I attack the goblin")
        assert result["type"] == "attack"

    def test_attack_extracts_target_goblin(self, parser):
        result = parser.parse("I attack the goblin")
        assert result["target"] == "goblin"

    def test_attack_extracts_target_orc(self, parser):
        result = parser.parse("I strike the orc with my sword")
        assert result["target"] == "orc"

    def test_attack_slash(self, parser):
        result = parser.parse("I slash at the skeleton")
        assert result["type"] == "attack"
        assert result["target"] == "skeleton"

    def test_attack_shoot(self, parser):
        result = parser.parse("I shoot the goblin with my bow")
        assert result["type"] == "attack"


class TestSpellParsing:
    def test_cast_firebolt(self, parser):
        result = parser.parse("I cast firebolt at the goblin")
        assert result["type"] == "spell"

    def test_cast_extracts_spell_name(self, parser):
        result = parser.parse("I cast fire bolt on the orc")
        assert result["spell_name"] in ("fire_bolt", "firebolt")

    def test_cast_magic_missile(self, parser):
        result = parser.parse("cast magic missile at them")
        assert result["spell_name"] == "magic_missile"

    def test_spell_extracts_target(self, parser):
        result = parser.parse("I cast firebolt on the goblin")
        assert result["target"] == "goblin"

    def test_cure_wounds_detected(self, parser):
        result = parser.parse("I cast cure wounds on myself")
        assert result["type"] == "spell"
        assert result["spell_name"] == "cure_wounds"


class TestSkillChecks:
    def test_stealth_check(self, parser):
        result = parser.parse("I try to sneak past the guards")
        assert result["type"] == "skill_check"
        assert result["skill"] == "stealth"

    def test_perception_check(self, parser):
        result = parser.parse("I look around the room carefully")
        assert result["type"] == "skill_check"
        assert result["skill"] == "perception"

    def test_investigation_check(self, parser):
        result = parser.parse("I investigate the ancient ruins")
        assert result["type"] == "skill_check"
        assert result["skill"] == "investigation"

    def test_athletics_check(self, parser):
        result = parser.parse("I try to climb the wall")
        assert result["type"] == "skill_check"
        assert result["skill"] == "athletics"

    def test_persuasion_check(self, parser):
        result = parser.parse("I try to persuade the merchant")
        assert result["type"] == "skill_check"
        assert result["skill"] == "persuasion"

    def test_deception_check(self, parser):
        result = parser.parse("I lie to the guard about my identity")
        assert result["type"] == "skill_check"
        assert result["skill"] == "deception"

    def test_intimidation_check(self, parser):
        result = parser.parse("I intimidate the prisoner")
        assert result["type"] == "skill_check"
        assert result["skill"] == "intimidation"

    def test_thieves_tools(self, parser):
        result = parser.parse("I try to pick the lock")
        assert result["type"] == "skill_check"
        assert result["skill"] == "thieves_tools"


class TestInitiative:
    def test_roll_for_initiative(self, parser):
        result = parser.parse("roll for initiative")
        assert result["type"] == "initiative"

    def test_start_combat(self, parser):
        result = parser.parse("I start combat")
        assert result["type"] == "initiative"

    def test_draw_weapon(self, parser):
        result = parser.parse("I draw my weapon")
        assert result["type"] == "initiative"


class TestCombatActions:
    def test_dodge(self, parser):
        result = parser.parse("I dodge the attack")
        assert result["type"] == "dodge"

    def test_dash(self, parser):
        result = parser.parse("I dash away")
        assert result["type"] == "dash"

    def test_disengage(self, parser):
        result = parser.parse("I disengage from the goblin")
        assert result["type"] == "disengage"


class TestItemUse:
    def test_drink_healing_potion(self, parser):
        result = parser.parse("I drink a healing potion")
        assert result["type"] == "use_item"
        assert result["item_name"] == "healing_potion"

    def test_use_potion(self, parser):
        result = parser.parse("use potion")
        assert result["type"] == "use_item"


class TestMetaCommands:
    def test_inventory_check(self, parser):
        result = parser.parse("check my inventory")
        assert result["type"] == "meta"
        assert result["meta_command"] == "inventory"

    def test_stats_check(self, parser):
        result = parser.parse("check my stats")
        assert result["type"] == "meta"
        assert result["meta_command"] == "stats"

    def test_quest_log(self, parser):
        result = parser.parse("quest log")
        assert result["type"] == "meta"
        assert result["meta_command"] == "quests"

    def test_save_game(self, parser):
        result = parser.parse("save game")
        assert result["type"] == "meta"
        assert result["meta_command"] == "save"

    def test_help(self, parser):
        result = parser.parse("help")
        assert result["type"] == "meta"
        assert result["meta_command"] == "help"


class TestNarrativeFallback:
    def test_unknown_input_is_narrative(self, parser):
        result = parser.parse("I sit down by the fire and think")
        assert result["type"] == "narrative"

    def test_original_intent_preserved(self, parser):
        text = "I open the mysterious chest carefully"
        result = parser.parse(text)
        assert result["intent"] == text

    def test_all_results_have_required_keys(self, parser):
        required_keys = {"type", "skill", "target", "spell_name",
                         "item_name", "meta_command", "intent"}
        test_inputs = [
            "attack goblin", "cast firebolt", "sneak past guard",
            "check my stats", "help", "I sit down"
        ]
        for text in test_inputs:
            result = parser.parse(text)
            assert required_keys.issubset(result.keys()), \
                f"Missing keys in result for '{text}': {required_keys - result.keys()}"
