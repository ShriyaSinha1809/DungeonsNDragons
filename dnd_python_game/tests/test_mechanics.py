"""Tests for mechanics.py — pure D&D 5e math engine."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from src.mechanics import DieRoll, DieRollResult, MechanicsEngine, EntitySnapshot, SKILL_ABILITY_MAP


# ---------------------------------------------------------------------------
# DieRoll.parse_notation
# ---------------------------------------------------------------------------

class TestParseNotation:
    def test_standard_notation(self):
        assert DieRoll.parse_notation("2d6+3") == (2, 6, 3)

    def test_notation_no_modifier(self):
        assert DieRoll.parse_notation("1d20") == (1, 20, 0)

    def test_notation_multi_dice(self):
        assert DieRoll.parse_notation("4d6") == (4, 6, 0)

    def test_notation_negative_modifier(self):
        assert DieRoll.parse_notation("1d8-2") == (1, 8, -2)

    def test_flat_modifier(self):
        nd, ds, mod = DieRoll.parse_notation("5")
        assert mod == 5

    def test_implicit_one_die(self):
        nd, ds, mod = DieRoll.parse_notation("d20")
        assert nd == 1 and ds == 20

    def test_damage_die_with_plus(self):
        nd, ds, mod = DieRoll.parse_notation("1d6+2")
        assert nd == 1 and ds == 6 and mod == 2


# ---------------------------------------------------------------------------
# DieRoll.roll
# ---------------------------------------------------------------------------

class TestDieRoll:
    def test_roll_returns_die_roll_result(self):
        result = DieRoll("1d20").roll()
        assert isinstance(result, DieRollResult)

    def test_roll_value_in_range(self):
        for _ in range(50):
            result = DieRoll("1d20").roll()
            assert 1 <= result.total <= 20

    def test_roll_2d6_range(self):
        for _ in range(50):
            result = DieRoll("2d6").roll()
            assert 2 <= result.total <= 12

    def test_roll_modifier_applied(self):
        for _ in range(30):
            result = DieRoll("1d6+3").roll()
            assert 4 <= result.total <= 9

    def test_advantage_picks_higher(self):
        """With enough samples, advantage mean should exceed neutral mean."""
        adv_totals = [DieRoll("1d20", advantage=True).roll().total for _ in range(200)]
        neutral_totals = [DieRoll("1d20").roll().total for _ in range(200)]
        assert sum(adv_totals) / len(adv_totals) > sum(neutral_totals) / len(neutral_totals)

    def test_disadvantage_picks_lower(self):
        """With enough samples, disadvantage mean should be below neutral mean."""
        disadv_totals = [DieRoll("1d20", disadvantage=True).roll().total for _ in range(200)]
        neutral_totals = [DieRoll("1d20").roll().total for _ in range(200)]
        assert sum(disadv_totals) / len(disadv_totals) < sum(neutral_totals) / len(neutral_totals)

    def test_crit_doubles_dice_count(self):
        """Critical hit rolls 2d6 instead of 1d6."""
        normal_max = 6
        crit_max = 12  # 2d6 max
        crit_results = [DieRoll("1d6", crit=True).roll().total for _ in range(50)]
        # At least one roll should exceed the normal max (very likely over 50 trials)
        assert any(r > normal_max for r in crit_results)

    def test_nat_20_detection(self):
        """Force a nat 20 by mocking random."""
        import unittest.mock as mock
        with mock.patch("random.randint", return_value=20):
            result = DieRoll("1d20").roll()
            assert result.is_nat_20

    def test_nat_1_detection(self):
        import unittest.mock as mock
        with mock.patch("random.randint", return_value=1):
            result = DieRoll("1d20").roll()
            assert result.is_nat_1

    def test_advantage_disadv_cancel(self):
        """If both advantage and disadvantage, neither applies (straight roll)."""
        result = DieRoll("1d20", advantage=True, disadvantage=True).roll()
        # Should not have either flag set
        assert not result.advantage
        assert not result.disadvantage


# ---------------------------------------------------------------------------
# MechanicsEngine.ability_modifier
# ---------------------------------------------------------------------------

class TestAbilityModifier:
    def setup_method(self):
        self.engine = MechanicsEngine()

    def test_score_10_gives_zero(self):
        assert self.engine.ability_modifier(10) == 0

    def test_score_11_gives_zero(self):
        assert self.engine.ability_modifier(11) == 0

    def test_score_12_gives_plus_one(self):
        assert self.engine.ability_modifier(12) == 1

    def test_score_20_gives_plus_five(self):
        assert self.engine.ability_modifier(20) == 5

    def test_score_8_gives_minus_one(self):
        assert self.engine.ability_modifier(8) == -1

    def test_score_1_gives_minus_five(self):
        assert self.engine.ability_modifier(1) == -5

    def test_score_18_gives_plus_four(self):
        assert self.engine.ability_modifier(18) == 4


# ---------------------------------------------------------------------------
# MechanicsEngine.proficiency_bonus
# ---------------------------------------------------------------------------

class TestProficiencyBonus:
    def setup_method(self):
        self.engine = MechanicsEngine()

    def test_level_1_gives_2(self):
        assert self.engine.proficiency_bonus(1) == 2

    def test_level_4_gives_2(self):
        assert self.engine.proficiency_bonus(4) == 2

    def test_level_5_gives_3(self):
        assert self.engine.proficiency_bonus(5) == 3

    def test_level_9_gives_4(self):
        assert self.engine.proficiency_bonus(9) == 4

    def test_level_17_gives_6(self):
        assert self.engine.proficiency_bonus(17) == 6

    def test_level_20_gives_6(self):
        assert self.engine.proficiency_bonus(20) == 6


# ---------------------------------------------------------------------------
# MechanicsEngine.resolve_attack
# ---------------------------------------------------------------------------

def _make_snapshot(name="Hero", level=1, str_score=16, dex_score=14, ac=15,
                   conditions=None, char_class="fighter", proficient_skills=None,
                   proficient_saves=None, hp=20, max_hp=20) -> EntitySnapshot:
    return EntitySnapshot(
        name=name,
        level=level,
        ability_scores={"str": str_score, "dex": dex_score, "con": 14,
                        "int": 10, "wis": 10, "cha": 10},
        proficient_skills=proficient_skills or [],
        proficient_saves=proficient_saves or [],
        equipped={"main_hand": "longsword"},
        conditions=conditions or [],
        char_class=char_class,
        ac=ac,
        hp=hp,
        max_hp=max_hp,
    )


class TestResolveAttack:
    def setup_method(self):
        self.engine = MechanicsEngine()
        self.weapon = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing",
                       "type": "melee_attack", "properties": [], "range": 5}

    def test_nat_1_always_misses(self):
        import unittest.mock as mock
        attacker = _make_snapshot(level=5)
        target = _make_snapshot(ac=1)  # AC 1 — should always hit normally
        with mock.patch("random.randint", return_value=1):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert not result.hit

    def test_nat_20_always_hits(self):
        import unittest.mock as mock
        attacker = _make_snapshot()
        target = _make_snapshot(ac=30)  # impossible AC
        with mock.patch("random.randint", return_value=20):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert result.hit

    def test_nat_20_is_crit(self):
        import unittest.mock as mock
        attacker = _make_snapshot()
        target = _make_snapshot(ac=30)
        with mock.patch("random.randint", return_value=20):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert result.crit

    def test_hit_when_roll_exceeds_ac(self):
        import unittest.mock as mock
        attacker = _make_snapshot(str_score=10, level=1)  # +0 str, +2 prof = +2 atk mod
        target = _make_snapshot(ac=10)
        with mock.patch("random.randint", return_value=15):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert result.hit

    def test_miss_when_roll_below_ac(self):
        import unittest.mock as mock
        attacker = _make_snapshot(str_score=10, level=1)
        target = _make_snapshot(ac=20)
        with mock.patch("random.randint", return_value=5):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert not result.hit

    def test_no_damage_on_miss(self):
        import unittest.mock as mock
        attacker = _make_snapshot(str_score=10, level=1)
        target = _make_snapshot(ac=20)
        with mock.patch("random.randint", return_value=2):
            result = self.engine.resolve_attack(attacker, target, self.weapon)
        assert result.damage == 0

    def test_finesse_uses_better_modifier(self):
        finesse_weapon = {"name": "Dagger", "damage": "1d4", "damage_type": "piercing",
                          "type": "melee_attack", "properties": ["finesse"], "range": 5}
        # High DEX (18 = +4), low STR (8 = -1) → should use DEX
        attacker = _make_snapshot(str_score=8, dex_score=18, level=1)
        target = _make_snapshot(ac=1)
        import unittest.mock as mock
        with mock.patch("random.randint", return_value=10):
            result = self.engine.resolve_attack(attacker, target, finesse_weapon)
        # attack_total should be 10 + 4 (DEX) + 2 (prof) = 16 vs AC 1 → hit
        assert result.hit


# ---------------------------------------------------------------------------
# MechanicsEngine.resolve_skill_check
# ---------------------------------------------------------------------------

class TestResolveSkillCheck:
    def setup_method(self):
        self.engine = MechanicsEngine()

    def test_proficient_skill_adds_bonus(self):
        import unittest.mock as mock
        entity = _make_snapshot(dex_score=14, level=1, proficient_skills=["stealth"])
        with mock.patch("random.randint", return_value=10):
            result = self.engine.resolve_skill_check(entity, "stealth", dc=12)
        # total = 10 (roll) + 2 (DEX mod) + 2 (prof) = 14 >= 12 → success
        assert result.success
        assert result.total == 14

    def test_non_proficient_skill(self):
        import unittest.mock as mock
        entity = _make_snapshot(dex_score=10, level=1, proficient_skills=[])
        with mock.patch("random.randint", return_value=5):
            result = self.engine.resolve_skill_check(entity, "stealth", dc=12)
        # total = 5 + 0 (DEX mod) + 0 (no prof) = 5 → fail
        assert not result.success

    def test_skill_ability_mapping_coverage(self):
        """All skills in SKILL_ABILITY_MAP resolve without error."""
        entity = _make_snapshot()
        for skill in SKILL_ABILITY_MAP:
            result = self.engine.resolve_skill_check(entity, skill, dc=10)
            assert isinstance(result.success, bool)


# ---------------------------------------------------------------------------
# MechanicsEngine.resolve_saving_throw
# ---------------------------------------------------------------------------

class TestResolveSavingThrow:
    def setup_method(self):
        self.engine = MechanicsEngine()

    def test_proficient_save_adds_bonus(self):
        import unittest.mock as mock
        entity = _make_snapshot(level=1, proficient_saves=["con"])
        with mock.patch("random.randint", return_value=8):
            result = self.engine.resolve_saving_throw(entity, "con", dc=12)
        # 8 + 2 (CON mod from score 14) + 2 (prof) = 12 >= 12 → success
        assert result.success

    def test_failed_save(self):
        import unittest.mock as mock
        entity = _make_snapshot(level=1, proficient_saves=[])
        entity.ability_scores["con"] = 8  # -1 mod
        with mock.patch("random.randint", return_value=3):
            result = self.engine.resolve_saving_throw(entity, "con", dc=15)
        assert not result.success


# ---------------------------------------------------------------------------
# MechanicsEngine.resolve_death_save
# ---------------------------------------------------------------------------

class TestResolveDeathSave:
    def setup_method(self):
        self.engine = MechanicsEngine()

    def test_nat_20_stabilizes(self):
        import unittest.mock as mock
        entity = _make_snapshot(ac=0, hp=0)
        with mock.patch("random.randint", return_value=20):
            result = self.engine.resolve_death_save(entity)
        assert result.nat_20
        assert result.stabilized

    def test_nat_1_marked(self):
        import unittest.mock as mock
        entity = _make_snapshot(ac=0, hp=0)
        with mock.patch("random.randint", return_value=1):
            result = self.engine.resolve_death_save(entity)
        assert result.nat_1

    def test_roll_10_is_success(self):
        import unittest.mock as mock
        entity = _make_snapshot(ac=0, hp=0)
        with mock.patch("random.randint", return_value=10):
            result = self.engine.resolve_death_save(entity)
        assert result.success

    def test_roll_9_is_failure(self):
        import unittest.mock as mock
        entity = _make_snapshot(ac=0, hp=0)
        with mock.patch("random.randint", return_value=9):
            result = self.engine.resolve_death_save(entity)
        assert not result.success
