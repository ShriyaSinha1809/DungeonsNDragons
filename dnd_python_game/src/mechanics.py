"""
mechanics.py - Pure D&D 5e rules engine.
No I/O, no state mutation. All functions receive snapshots and return results.
Ported from natural_20 Ruby gem (lib/natural_20/die_roll.rb, concerns/entity.rb,
actions/attack_action.rb).
"""
import random
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Skill → governing ability mapping (all 18 skills)
# ---------------------------------------------------------------------------
SKILL_ABILITY_MAP: dict[str, str] = {
    "athletics": "str",
    "acrobatics": "dex",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    "arcana": "int",
    "history": "int",
    "investigation": "int",
    "nature": "int",
    "religion": "int",
    "animal_handling": "wis",
    "insight": "wis",
    "medicine": "wis",
    "perception": "wis",
    "survival": "wis",
    "deception": "cha",
    "intimidation": "cha",
    "performance": "cha",
    "persuasion": "cha",
    # Tool skills
    "thieves_tools": "dex",
}

# Standard 5e XP thresholds per level (index = level - 1)
XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000,
                 64000, 85000, 100000, 120000, 140000, 165000, 195000,
                 225000, 265000, 305000, 355000]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DieRollResult:
    rolls: list[int]          # all rolled values (pairs for adv/disadv)
    selected_rolls: list[int] # rolls actually used after adv/disadv selection
    modifier: int
    die_sides: int
    num_dice: int
    advantage: bool
    disadvantage: bool
    crit: bool

    @property
    def total(self) -> int:
        return sum(self.selected_rolls) + self.modifier

    @property
    def is_nat_20(self) -> bool:
        # For a d20 roll: the selected single die is 20
        if self.die_sides == 20 and self.num_dice == 1:
            return self.selected_rolls[0] == 20
        return False

    @property
    def is_nat_1(self) -> bool:
        if self.die_sides == 20 and self.num_dice == 1:
            return self.selected_rolls[0] == 1
        return False

    def __str__(self) -> str:
        parts = []
        if self.advantage:
            parts.append(f"[adv: {self.rolls}→{self.selected_rolls}]")
        elif self.disadvantage:
            parts.append(f"[disadv: {self.rolls}→{self.selected_rolls}]")
        else:
            parts.append(str(self.selected_rolls))
        if self.modifier != 0:
            sign = "+" if self.modifier > 0 else ""
            parts.append(f"{sign}{self.modifier}")
        parts.append(f"= {self.total}")
        return " ".join(parts)


@dataclass
class AttackResult:
    hit: bool
    crit: bool
    damage: int
    attack_roll: int
    attack_total: int
    target_ac: int
    damage_roll_detail: DieRollResult
    weapon_name: str
    attacker_name: str
    target_name: str

    def mechanical_summary(self) -> str:
        result = "CRIT HIT" if self.crit else ("HIT" if self.hit else "MISS")
        return (f"Attack: d20={self.attack_roll} total={self.attack_total} "
                f"vs AC {self.target_ac} → {result}"
                + (f" | Damage: {self.damage_roll_detail}" if self.hit else ""))


@dataclass
class SkillCheckResult:
    success: bool
    roll: int
    total: int
    dc: int
    skill: str
    ability: str

    def mechanical_summary(self) -> str:
        result = "SUCCESS" if self.success else "FAILURE"
        return f"{self.skill.title()} check: {self.total} vs DC {self.dc} → {result}"


@dataclass
class SavingThrowResult:
    success: bool
    roll: int
    total: int
    ability: str
    dc: int

    def mechanical_summary(self) -> str:
        result = "PASSED" if self.success else "FAILED"
        return f"{self.ability.upper()} save: {self.total} vs DC {self.dc} → {result}"


@dataclass
class SpellResult:
    hit: bool
    damage: int
    effect: str
    spell_name: str
    spell_level: int
    roll_detail: Optional[DieRollResult]
    is_auto_hit: bool = False
    is_healing: bool = False
    heal_amount: int = 0

    def mechanical_summary(self) -> str:
        if self.is_healing:
            return f"{self.spell_name}: heals {self.heal_amount} HP"
        if self.is_auto_hit:
            return f"{self.spell_name}: auto-hit for {self.damage} damage"
        result = "HIT" if self.hit else "MISS"
        return f"{self.spell_name}: {result} | Damage: {self.damage}"


@dataclass
class DeathSaveResult:
    roll: int
    success: bool
    nat_20: bool
    nat_1: bool
    stabilized: bool

    def mechanical_summary(self) -> str:
        if self.nat_20:
            return f"Death save: {self.roll} — NAT 20! Regain 1 HP!"
        if self.nat_1:
            return f"Death save: {self.roll} — NAT 1! Two failures!"
        result = "Success" if self.success else "Failure"
        return f"Death save: {self.roll} — {result}"


# ---------------------------------------------------------------------------
# DieRoll — ported from natural_20/lib/natural_20/die_roll.rb
# ---------------------------------------------------------------------------

class DieRoll:
    """
    Parse and roll dice notation like '2d6+3', '1d20', '4d6'.
    Supports advantage/disadvantage (roll each die twice, keep max/min).
    Supports critical hits (double the number of dice).
    """

    def __init__(
        self,
        notation: str,
        advantage: bool = False,
        disadvantage: bool = False,
        crit: bool = False
    ):
        self.notation = notation
        self.advantage = advantage and not disadvantage
        self.disadvantage = disadvantage and not advantage
        self.crit = crit

    @staticmethod
    def parse_notation(notation: str) -> tuple[int, int, int]:
        """
        Returns (num_dice, die_sides, modifier).
        '2d6+3' → (2, 6, 3)
        '1d20'  → (1, 20, 0)
        '4d6'   → (4, 6, 0)
        '1d4+1' → (1, 4, 1)
        '5'     → (0, 0, 5)   pure flat modifier
        """
        notation = notation.strip().lower().replace(" ", "")
        # Match patterns like 2d6+3, 1d8-2, 3d6, d20
        m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", notation)
        if m:
            num_dice = int(m.group(1)) if m.group(1) else 1
            die_sides = int(m.group(2))
            modifier = int(m.group(3)) if m.group(3) else 0
            return num_dice, die_sides, modifier
        # Pure flat number
        try:
            return 0, 0, int(notation)
        except ValueError:
            return 1, 6, 0  # fallback

    def roll(self) -> DieRollResult:
        num_dice, die_sides, modifier = self.parse_notation(self.notation)

        # Critical: double the dice rolled (ported from Ruby: number_of_die *= 2 if crit)
        if self.crit and num_dice > 0:
            num_dice *= 2

        if die_sides == 0:
            # Pure flat value
            return DieRollResult(
                rolls=[modifier],
                selected_rolls=[modifier],
                modifier=0,
                die_sides=0,
                num_dice=0,
                advantage=self.advantage,
                disadvantage=self.disadvantage,
                crit=self.crit
            )

        all_rolls = []
        selected_rolls = []

        for _ in range(num_dice):
            if self.advantage or self.disadvantage:
                r1 = random.randint(1, die_sides)
                r2 = random.randint(1, die_sides)
                all_rolls.extend([r1, r2])
                if self.advantage:
                    selected_rolls.append(max(r1, r2))
                else:
                    selected_rolls.append(min(r1, r2))
            else:
                r = random.randint(1, die_sides)
                all_rolls.append(r)
                selected_rolls.append(r)

        return DieRollResult(
            rolls=all_rolls,
            selected_rolls=selected_rolls,
            modifier=modifier,
            die_sides=die_sides,
            num_dice=num_dice,
            advantage=self.advantage,
            disadvantage=self.disadvantage,
            crit=self.crit
        )


def roll(notation: str, advantage: bool = False, disadvantage: bool = False,
         crit: bool = False) -> DieRollResult:
    """Convenience function wrapping DieRoll."""
    return DieRoll(notation, advantage=advantage, disadvantage=disadvantage, crit=crit).roll()


# ---------------------------------------------------------------------------
# Entity snapshot (thin dict-based view passed into mechanics)
# ---------------------------------------------------------------------------

class EntitySnapshot:
    """
    Lightweight view of a PlayerState or NPCState for mechanics calculations.
    Avoids circular imports — mechanics.py never imports state_manager.py.
    """

    def __init__(
        self,
        name: str,
        level: int,
        ability_scores: dict,    # {"str": 16, "dex": 14, ...}
        proficient_skills: list[str],
        proficient_saves: list[str],
        equipped: dict,          # {"main_hand": "longsword", "armor": "chain_mail"}
        conditions: list[str],
        char_class: str,
        ac: int,
        hp: int,
        max_hp: int,
        spell_slots: dict = None,
        known_spells: list[str] = None,
    ):
        self.name = name
        self.level = level
        self.ability_scores = ability_scores
        self.proficient_skills = proficient_skills or []
        self.proficient_saves = proficient_saves or []
        self.equipped = equipped or {}
        self.conditions = conditions or []
        self.char_class = char_class
        self.ac = ac
        self.hp = hp
        self.max_hp = max_hp
        self.spell_slots = spell_slots or {}
        self.known_spells = known_spells or []


# ---------------------------------------------------------------------------
# MechanicsEngine
# ---------------------------------------------------------------------------

class MechanicsEngine:
    """
    Stateless D&D 5e mechanics resolver.
    All methods take EntitySnapshot objects and return result dataclasses.
    """

    # Standard 5e proficiency bonus table indexed by (level - 1)
    PROFICIENCY_TABLE = [2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6]

    def ability_modifier(self, score: int) -> int:
        """Standard 5e: floor((score - 10) / 2)"""
        return (score - 10) // 2

    def proficiency_bonus(self, level: int) -> int:
        idx = max(0, min(level - 1, len(self.PROFICIENCY_TABLE) - 1))
        return self.PROFICIENCY_TABLE[idx]

    def _get_ability_mod(self, entity: EntitySnapshot, ability: str) -> int:
        score = entity.ability_scores.get(ability, 10)
        return self.ability_modifier(score)

    def _is_proficient_skill(self, entity: EntitySnapshot, skill: str) -> bool:
        return skill in entity.proficient_skills

    def _is_proficient_save(self, entity: EntitySnapshot, ability: str) -> bool:
        return ability in entity.proficient_saves

    def _weapon_attack_modifier(
        self, attacker: EntitySnapshot, weapon_data: dict
    ) -> int:
        """
        Calculate attack roll modifier for a weapon.
        Finesse weapons use the better of STR or DEX.
        Ranged weapons use DEX.
        """
        props = weapon_data.get("properties", [])
        attack_type = weapon_data.get("type", "melee_attack")

        str_mod = self._get_ability_mod(attacker, "str")
        dex_mod = self._get_ability_mod(attacker, "dex")

        if "finesse" in props:
            ability_mod = max(str_mod, dex_mod)
        elif attack_type == "ranged_attack":
            ability_mod = dex_mod
        else:
            ability_mod = str_mod

        prof = self.proficiency_bonus(attacker.level)
        return ability_mod + prof

    def _weapon_damage_modifier(
        self, attacker: EntitySnapshot, weapon_data: dict
    ) -> int:
        """Damage modifier (ability mod only, no proficiency)."""
        props = weapon_data.get("properties", [])
        attack_type = weapon_data.get("type", "melee_attack")

        str_mod = self._get_ability_mod(attacker, "str")
        dex_mod = self._get_ability_mod(attacker, "dex")

        if "finesse" in props:
            return max(str_mod, dex_mod)
        elif attack_type == "ranged_attack":
            return dex_mod
        return str_mod

    def resolve_attack(
        self,
        attacker: EntitySnapshot,
        target: EntitySnapshot,
        weapon_data: dict,
        advantage: bool = False,
        disadvantage: bool = False
    ) -> AttackResult:
        """
        Full D&D 5e attack resolution.
        nat 1 always misses, nat 20 always hits and crits.
        """
        attack_mod = self._weapon_attack_modifier(attacker, weapon_data)

        # Roll d20 for attack
        attack_result = DieRoll("1d20", advantage=advantage, disadvantage=disadvantage).roll()
        raw_roll = attack_result.selected_rolls[0]
        attack_total = raw_roll + attack_mod

        # Determine hit/miss/crit
        if raw_roll == 1:
            hit, crit = False, False
        elif raw_roll == 20:
            hit, crit = True, True
        else:
            hit = attack_total >= target.ac
            crit = False

        # Roll damage
        damage_die = weapon_data.get("damage", "1d4")
        # Strip existing modifier from damage_die string (we add it ourselves)
        # e.g. "1d6+2" from NPC actions: use as-is
        dmg_result = DieRoll(damage_die, crit=crit).roll()
        # Add ability modifier on top of what's already in the notation
        dmg_modifier = self._weapon_damage_modifier(attacker, weapon_data)

        # Clamp damage to >= 1 if it hit
        damage = max(1, dmg_result.total + (0 if "+" in damage_die or "-" in damage_die else dmg_modifier)) if hit else 0

        return AttackResult(
            hit=hit,
            crit=crit,
            damage=damage,
            attack_roll=raw_roll,
            attack_total=attack_total,
            target_ac=target.ac,
            damage_roll_detail=dmg_result,
            weapon_name=weapon_data.get("name", "weapon"),
            attacker_name=attacker.name,
            target_name=target.name
        )

    def resolve_skill_check(
        self,
        entity: EntitySnapshot,
        skill: str,
        dc: int,
        advantage: bool = False,
        disadvantage: bool = False
    ) -> SkillCheckResult:
        """d20 + ability_mod + proficiency_bonus (if proficient) vs DC."""
        ability = SKILL_ABILITY_MAP.get(skill, "wis")
        ability_mod = self._get_ability_mod(entity, ability)
        prof_bonus = self.proficiency_bonus(entity.level) if self._is_proficient_skill(entity, skill) else 0

        result = DieRoll("1d20", advantage=advantage, disadvantage=disadvantage).roll()
        raw_roll = result.selected_rolls[0]
        total = raw_roll + ability_mod + prof_bonus

        return SkillCheckResult(
            success=total >= dc,
            roll=raw_roll,
            total=total,
            dc=dc,
            skill=skill,
            ability=ability
        )

    def resolve_saving_throw(
        self,
        entity: EntitySnapshot,
        ability: str,
        dc: int,
        advantage: bool = False,
        disadvantage: bool = False
    ) -> SavingThrowResult:
        """d20 + ability_mod + proficiency_bonus (if proficient in save) vs DC."""
        ability_mod = self._get_ability_mod(entity, ability)
        prof_bonus = self.proficiency_bonus(entity.level) if self._is_proficient_save(entity, ability) else 0

        result = DieRoll("1d20", advantage=advantage, disadvantage=disadvantage).roll()
        raw_roll = result.selected_rolls[0]
        total = raw_roll + ability_mod + prof_bonus

        return SavingThrowResult(
            success=total >= dc,
            roll=raw_roll,
            total=total,
            ability=ability,
            dc=dc
        )

    def resolve_spell_attack(
        self,
        caster: EntitySnapshot,
        target: EntitySnapshot,
        spell_data: dict,
        slot_level: int = 1
    ) -> SpellResult:
        """
        Resolves a spell attack of any type:
        - ranged_attack / melee_spell_attack: roll to hit vs AC
        - auto_hit (magic missile): always hits
        - saving_throw: target makes a save
        - healing: heals the caster or target
        - buff: no roll needed
        """
        spell_name = spell_data.get("name", "Spell")
        spell_type = spell_data.get("type", "ranged_attack")
        spell_level = spell_data.get("level", 0)

        # Spellcasting ability: int for wizard, wis for cleric, cha for sorcerer/bard
        # Default to int
        casting_ability = "int"
        if caster.char_class.lower() in ("cleric", "druid", "ranger"):
            casting_ability = "wis"
        elif caster.char_class.lower() in ("sorcerer", "bard", "paladin", "warlock"):
            casting_ability = "cha"

        casting_mod = self._get_ability_mod(caster, casting_ability)
        prof = self.proficiency_bonus(caster.level)
        spell_attack_bonus = casting_mod + prof
        save_dc = 8 + casting_mod + prof

        if spell_type == "healing":
            base_heal = spell_data.get("base_heal", "1d8")
            heal_roll = DieRoll(base_heal).roll()
            heal_amount = heal_roll.total + casting_mod
            return SpellResult(
                hit=True, damage=0, effect="healing",
                spell_name=spell_name, spell_level=spell_level,
                roll_detail=heal_roll, is_healing=True,
                heal_amount=max(1, heal_amount)
            )

        if spell_type == "buff":
            return SpellResult(
                hit=True, damage=0, effect=spell_data.get("description", "buff"),
                spell_name=spell_name, spell_level=spell_level,
                roll_detail=None
            )

        # Scale damage for higher-level slots
        base_damage = spell_data.get("base_damage", "1d6")
        damage_increase_levels = spell_data.get("damage_increase", [])
        extra_dice = sum(1 for lvl in damage_increase_levels if slot_level >= lvl)
        # For cantrip scaling based on character level
        if spell_level == 0:
            extra_dice = sum(1 for lvl in damage_increase_levels if caster.level >= lvl)

        # Parse base damage notation to scale it
        nd, ds, dm = DieRoll.parse_notation(base_damage)
        actual_notation = f"{nd + extra_dice}d{ds}{'+' + str(dm) if dm > 0 else ('-' + str(abs(dm)) if dm < 0 else '')}" if ds > 0 else base_damage

        if spell_type == "auto_hit":
            missiles = spell_data.get("missiles", 1)
            # Each missile does base_damage
            total_damage = 0
            last_roll = None
            for _ in range(missiles):
                r = DieRoll(base_damage).roll()
                total_damage += r.total
                last_roll = r
            return SpellResult(
                hit=True, damage=total_damage, effect="force damage",
                spell_name=spell_name, spell_level=spell_level,
                roll_detail=last_roll, is_auto_hit=True
            )

        if spell_type == "saving_throw":
            save_ability = spell_data.get("save_ability", "dex")
            dc = spell_data.get("dc_base", 8) + casting_mod + prof
            save_result = self.resolve_saving_throw(target, save_ability, dc)
            dmg_roll = DieRoll(actual_notation).roll()
            half_on_save = spell_data.get("half_on_save", False)
            if save_result.success:
                damage = dmg_roll.total // 2 if half_on_save else 0
            else:
                damage = dmg_roll.total
            return SpellResult(
                hit=not save_result.success, damage=damage,
                effect=f"{save_ability.upper()} save DC {dc}",
                spell_name=spell_name, spell_level=spell_level,
                roll_detail=dmg_roll
            )

        # ranged_attack or melee_spell_attack: roll to hit
        atk_result = DieRoll("1d20").roll()
        raw_roll = atk_result.selected_rolls[0]
        attack_total = raw_roll + spell_attack_bonus

        if raw_roll == 1:
            hit, crit = False, False
        elif raw_roll == 20:
            hit, crit = True, True
        else:
            hit = attack_total >= target.ac
            crit = False

        damage = 0
        dmg_roll = None
        if hit:
            dmg_roll = DieRoll(actual_notation, crit=crit).roll()
            damage = max(1, dmg_roll.total)

        return SpellResult(
            hit=hit, damage=damage,
            effect=spell_data.get("damage_type", "magical"),
            spell_name=spell_name, spell_level=spell_level,
            roll_detail=dmg_roll
        )

    def resolve_death_save(self, entity: EntitySnapshot) -> DeathSaveResult:
        """
        Roll death saving throw.
        nat 20: stabilize + regain 1 HP
        nat 1: counts as 2 failures
        10+: success
        <10: failure
        """
        result = DieRoll("1d20").roll()
        raw = result.selected_rolls[0]

        nat_20 = raw == 20
        nat_1 = raw == 1
        success = raw >= 10
        stabilized = nat_20

        return DeathSaveResult(
            roll=raw,
            success=success,
            nat_20=nat_20,
            nat_1=nat_1,
            stabilized=stabilized
        )

    def roll_initiative(self, entity: EntitySnapshot) -> int:
        """d20 + DEX modifier."""
        dex_mod = self._get_ability_mod(entity, "dex")
        result = DieRoll("1d20").roll()
        return result.selected_rolls[0] + dex_mod

    def level_from_xp(self, xp: int) -> int:
        """Return character level based on total XP."""
        level = 1
        for i, threshold in enumerate(XP_THRESHOLDS):
            if xp >= threshold:
                level = i + 1
        return level
