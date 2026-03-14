"""
combat.py - Full D&D 5e turn-based combat system.
Handles initiative, turn order, player/NPC actions, and post-combat resolution.
"""
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .state_manager import StateManager, NPCState, CombatState, PlayerState
from .mechanics import MechanicsEngine, EntitySnapshot


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CombatTurnResult:
    actor_id: str
    action_type: str
    target_id: Optional[str]
    success: bool
    damage_dealt: int
    narrative_summary: str
    mechanical_details: str
    state_changes: dict = field(default_factory=dict)


@dataclass
class PostCombatResult:
    xp_gained: int
    loot: list
    leveled_up: bool
    new_level: Optional[int]


# ---------------------------------------------------------------------------
# CombatManager
# ---------------------------------------------------------------------------

class CombatManager:
    def __init__(self, state_manager: StateManager, mechanics: MechanicsEngine):
        self.state = state_manager
        self.mechanics = mechanics
        self.console = Console()

    def is_in_combat(self) -> bool:
        cs = self.state.world.combat_state
        return cs is not None and cs.active

    def initiate_combat(self, npc_ids: list[str]) -> CombatState:
        """
        Roll initiative for player and each NPC, sort descending,
        create CombatState, and display the initiative order.
        """
        player = self.state.world.player
        if not player:
            raise RuntimeError("Cannot initiate combat: no player character.")

        player_snapshot = EntitySnapshot(**player.to_snapshot_dict())
        initiatives: dict[str, int] = {}

        # Roll player initiative
        player_init = self.mechanics.roll_initiative(player_snapshot)
        initiatives["player"] = player_init

        # Roll NPC initiatives
        for npc_id in npc_ids:
            npc = self.state.world.npcs.get(npc_id)
            if npc and npc.is_alive():
                npc_snapshot = EntitySnapshot(**npc.to_snapshot_dict())
                initiatives[npc_id] = self.mechanics.roll_initiative(npc_snapshot)

        # Sort by initiative (descending); DEX breaks ties
        def tiebreak(entity_id: str) -> tuple:
            init_val = initiatives[entity_id]
            if entity_id == "player":
                dex = player.ability_scores.dex
            else:
                npc = self.state.world.npcs.get(entity_id)
                dex = npc.ability_scores.dex if npc else 10
            return (init_val, dex)

        order = sorted(initiatives.keys(), key=tiebreak, reverse=True)
        combatants = {eid: ("player" if eid == "player" else "npc") for eid in order}

        combat_state = CombatState(
            initiative_order=order,
            current_turn_index=0,
            round_number=1,
            active=True,
            combatants=combatants,
        )
        self.state.world.combat_state = combat_state

        # Display initiative table
        table = Table(title="⚔  COMBAT BEGINS — Initiative Order", box=box.SIMPLE_HEAVY,
                      show_header=True, header_style="bold red")
        table.add_column("Order", style="dim", width=6)
        table.add_column("Name", style="bold")
        table.add_column("Initiative", style="yellow")
        table.add_column("HP", style="green")

        for i, eid in enumerate(order, 1):
            init_val = initiatives[eid]
            if eid == "player":
                name = f"[bold cyan]{player.name}[/bold cyan]"
                hp_str = f"{player.hp}/{player.max_hp}"
            else:
                npc = self.state.world.npcs[eid]
                name = f"[red]{npc.kind}[/red] ({eid})"
                hp_str = f"{npc.hp}/{npc.max_hp}"
            table.add_row(str(i), name, str(init_val), hp_str)

        self.console.print(table)
        return combat_state

    def process_player_turn(self, parsed_intent: dict) -> CombatTurnResult:
        """Dispatch player action to the appropriate resolver."""
        intent_type = parsed_intent.get("type", "narrative")

        if intent_type == "attack":
            return self._resolve_player_attack(parsed_intent)
        elif intent_type == "spell":
            return self._resolve_player_spell(parsed_intent)
        elif intent_type == "dodge":
            return self._apply_dodge_action()
        elif intent_type == "dash":
            return self._apply_dash_action()
        elif intent_type == "disengage":
            return self._apply_disengage_action()
        elif intent_type == "use_item":
            return self._resolve_use_item(parsed_intent)
        elif intent_type == "help":
            return self._apply_help_action(parsed_intent)
        else:
            # Pass-through for narrative actions during combat
            return CombatTurnResult(
                actor_id="player",
                action_type="narrative",
                target_id=None,
                success=True,
                damage_dealt=0,
                narrative_summary="Player attempts a creative action.",
                mechanical_details="No mechanical roll required.",
                state_changes={},
            )

    def process_npc_turns(self) -> list[CombatTurnResult]:
        """Execute all NPC turns in initiative order for this round."""
        results = []
        cs = self.state.world.combat_state
        if not cs:
            return results

        player = self.state.world.player
        if not player:
            return results

        for eid in cs.initiative_order:
            if eid == "player":
                continue
            npc = self.state.world.npcs.get(eid)
            if not npc or not npc.is_alive() or not npc.hostile:
                continue
            result = self._resolve_npc_attack(npc, player)
            results.append(result)

        return results

    def advance_turn(self) -> str:
        """Move to the next combatant, skipping the dead."""
        cs = self.state.world.combat_state
        if not cs:
            return ""

        dead_ids = set()
        for eid in cs.initiative_order:
            if eid == "player":
                if self.state.world.player and self.state.world.player.is_dead():
                    dead_ids.add(eid)
            else:
                npc = self.state.world.npcs.get(eid)
                if not npc or not npc.is_alive():
                    dead_ids.add(eid)

        return cs.advance_turn(dead_ids=dead_ids)

    def check_combat_end(self) -> Optional[str]:
        """
        Returns:
          "player_victory"     — all hostile NPCs dead
          "player_defeat"      — player dead (3 death save failures)
          "player_unconscious" — player HP <= 0, not yet dead
          None                 — combat continues
        """
        player = self.state.world.player
        if not player:
            return "player_defeat"

        if player.is_dead():
            return "player_defeat"

        if player.is_unconscious():
            return "player_unconscious"

        hostile_alive = self.state.world.get_hostile_npcs()
        if not hostile_alive:
            return "player_victory"

        return None

    def resolve_post_combat(self) -> PostCombatResult:
        """Award XP, collect loot, clear combat state."""
        total_xp = 0
        all_loot = []

        # Collect XP and loot from all defeated NPCs
        for npc in self.state.world.npcs.values():
            if not npc.is_alive() and npc.hostile:
                total_xp += npc.xp_value
                all_loot.extend(npc.inventory)

        leveled_up = self.state.award_xp(total_xp)
        new_level = self.state.world.player.level if leveled_up else None

        # Remove dead hostile NPCs from the world
        dead_ids = [nid for nid, npc in self.state.world.npcs.items()
                    if not npc.is_alive() and npc.hostile]
        for nid in dead_ids:
            self.state.world.remove_npc(nid)

        # Add loot to player inventory
        player = self.state.world.player
        if player:
            player.inventory.extend(all_loot)

        # Clear combat state
        self.state.world.combat_state = None

        return PostCombatResult(
            xp_gained=total_xp,
            loot=all_loot,
            leveled_up=leveled_up,
            new_level=new_level,
        )

    # ------------------------------------------------------------------
    # Player action resolvers
    # ------------------------------------------------------------------

    def _resolve_player_attack(self, parsed_intent: dict) -> CombatTurnResult:
        player = self.state.world.player
        target = self._find_target(parsed_intent.get("target"))
        if not target:
            return CombatTurnResult(
                actor_id="player",
                action_type="attack",
                target_id=None,
                success=False,
                damage_dealt=0,
                narrative_summary="No valid target found.",
                mechanical_details="No hostile NPCs in range.",
            )

        # Get weapon data
        main_hand = player.equipped.get("main_hand", "")
        weapon_data = self.state.get_weapon_data(main_hand) if main_hand else {}
        if not weapon_data:
            # Unarmed strike fallback
            weapon_data = {"name": "Unarmed Strike", "damage": "1", "type": "melee_attack",
                           "properties": [], "range": 5}

        # Difficulty modifiers
        config_mods = self.state.world.config.modifiers
        adv = config_mods.get("player_advantage", False)
        disadv = config_mods.get("player_disadvantage", False)

        player_snapshot = EntitySnapshot(**player.to_snapshot_dict())
        target_snapshot = EntitySnapshot(**target.to_snapshot_dict())

        result = self.mechanics.resolve_attack(
            player_snapshot, target_snapshot, weapon_data,
            advantage=adv, disadvantage=disadv
        )

        state_changes = {}
        if result.hit:
            target.hp = max(0, target.hp - result.damage)
            state_changes[f"{target.npc_id}_hp"] = target.hp
            if not target.is_alive():
                target.conditions.append("dead")

        summary = (
            f"You attack the {target.kind}! "
            + (f"[HIT] for {result.damage} {weapon_data.get('damage_type', 'physical')} damage!"
               if result.hit else "[MISS]")
        )
        if result.crit:
            summary = f"CRITICAL HIT! " + summary

        return CombatTurnResult(
            actor_id="player",
            action_type="attack",
            target_id=target.npc_id,
            success=result.hit,
            damage_dealt=result.damage,
            narrative_summary=summary,
            mechanical_details=result.mechanical_summary(),
            state_changes=state_changes,
        )

    def _resolve_player_spell(self, parsed_intent: dict) -> CombatTurnResult:
        player = self.state.world.player
        spell_name = parsed_intent.get("spell_name", "")
        spell_data = self.state.get_spell_data(spell_name) if spell_name else {}

        if not spell_data:
            return CombatTurnResult(
                actor_id="player",
                action_type="spell",
                target_id=None,
                success=False,
                damage_dealt=0,
                narrative_summary=f"You don't know the spell '{spell_name}'.",
                mechanical_details="Spell not found.",
            )

        # Check if it's a cantrip (level 0) or needs a spell slot
        spell_level = spell_data.get("level", 0)
        slot_key = str(spell_level)
        if spell_level > 0:
            available_slots = player.spell_slots.get(slot_key, 0)
            if available_slots <= 0:
                return CombatTurnResult(
                    actor_id="player",
                    action_type="spell",
                    target_id=None,
                    success=False,
                    damage_dealt=0,
                    narrative_summary=f"No level {spell_level} spell slots remaining!",
                    mechanical_details="Insufficient spell slots.",
                )
            player.spell_slots[slot_key] -= 1

        # Healing spells target the player
        spell_type = spell_data.get("type", "ranged_attack")
        if spell_type == "healing":
            player_snapshot = EntitySnapshot(**player.to_snapshot_dict())
            result = self.mechanics.resolve_spell_attack(
                player_snapshot, player_snapshot, spell_data, slot_level=spell_level
            )
            old_hp = player.hp
            player.hp = min(player.max_hp, player.hp + result.heal_amount)
            return CombatTurnResult(
                actor_id="player",
                action_type="spell",
                target_id="player",
                success=True,
                damage_dealt=0,
                narrative_summary=f"You cast {spell_data.get('name', spell_name)} and heal {result.heal_amount} HP.",
                mechanical_details=result.mechanical_summary(),
                state_changes={"player_hp": player.hp},
            )

        # Buff spells
        if spell_type == "buff":
            if spell_name == "mage_armor":
                # Set AC to 13 + DEX mod
                dex_mod = self.mechanics.ability_modifier(player.ability_scores.dex)
                new_ac = 13 + dex_mod
                player.ac = new_ac
                player.conditions.append("mage_armor")
                return CombatTurnResult(
                    actor_id="player",
                    action_type="spell",
                    target_id="player",
                    success=True,
                    damage_dealt=0,
                    narrative_summary=f"Mage Armor shimmers around you. AC is now {new_ac}.",
                    mechanical_details=f"AC set to {new_ac} (13 + DEX mod)",
                    state_changes={"player_ac": new_ac},
                )
            return CombatTurnResult(
                actor_id="player", action_type="spell", target_id="player",
                success=True, damage_dealt=0,
                narrative_summary=f"You cast {spell_data.get('name', spell_name)}.",
                mechanical_details="Buff applied.", state_changes={},
            )

        # Attack/damage spells — need a target
        target = self._find_target(parsed_intent.get("target"))
        if not target:
            return CombatTurnResult(
                actor_id="player", action_type="spell", target_id=None,
                success=False, damage_dealt=0,
                narrative_summary="No valid target for the spell.",
                mechanical_details="Target not found.",
            )

        player_snapshot = EntitySnapshot(**player.to_snapshot_dict())
        target_snapshot = EntitySnapshot(**target.to_snapshot_dict())

        result = self.mechanics.resolve_spell_attack(
            player_snapshot, target_snapshot, spell_data, slot_level=spell_level
        )

        state_changes = {}
        if result.hit and result.damage > 0:
            target.hp = max(0, target.hp - result.damage)
            state_changes[f"{target.npc_id}_hp"] = target.hp
            if not target.is_alive():
                target.conditions.append("dead")

        summary = (
            f"You cast {spell_data.get('name', spell_name)} at the {target.kind}! "
            + (f"[HIT] for {result.damage} {result.effect} damage!"
               if result.hit else "[MISSED]!")
        )

        return CombatTurnResult(
            actor_id="player",
            action_type="spell",
            target_id=target.npc_id,
            success=result.hit,
            damage_dealt=result.damage,
            narrative_summary=summary,
            mechanical_details=result.mechanical_summary(),
            state_changes=state_changes,
        )

    def _apply_dodge_action(self) -> CombatTurnResult:
        player = self.state.world.player
        if "dodging" not in player.conditions:
            player.conditions.append("dodging")
        return CombatTurnResult(
            actor_id="player",
            action_type="dodge",
            target_id=None,
            success=True,
            damage_dealt=0,
            narrative_summary="You take the Dodge action. Attackers have disadvantage until your next turn.",
            mechanical_details="Condition: dodging (disadvantage on attacks against you)",
            state_changes={"player_condition_added": "dodging"},
        )

    def _apply_dash_action(self) -> CombatTurnResult:
        return CombatTurnResult(
            actor_id="player",
            action_type="dash",
            target_id=None,
            success=True,
            damage_dealt=0,
            narrative_summary="You dash, doubling your movement speed this turn.",
            mechanical_details="Movement doubled for this turn.",
        )

    def _apply_disengage_action(self) -> CombatTurnResult:
        return CombatTurnResult(
            actor_id="player",
            action_type="disengage",
            target_id=None,
            success=True,
            damage_dealt=0,
            narrative_summary="You disengage, moving away without provoking opportunity attacks.",
            mechanical_details="No opportunity attacks triggered this turn.",
        )

    def _apply_help_action(self, parsed_intent: dict) -> CombatTurnResult:
        return CombatTurnResult(
            actor_id="player",
            action_type="help",
            target_id=parsed_intent.get("target"),
            success=True,
            damage_dealt=0,
            narrative_summary="You help an ally, granting them advantage on their next action.",
            mechanical_details="Ally gains advantage on next attack or check.",
        )

    def _resolve_use_item(self, parsed_intent: dict) -> CombatTurnResult:
        player = self.state.world.player
        item_name = parsed_intent.get("item_name", "healing_potion")

        # Find item in inventory
        item_entry = None
        for item in player.inventory:
            if item.get("type", "") == item_name and item.get("qty", 0) > 0:
                item_entry = item
                break

        if not item_entry:
            return CombatTurnResult(
                actor_id="player",
                action_type="use_item",
                target_id=None,
                success=False,
                damage_dealt=0,
                narrative_summary=f"You don't have any {item_name.replace('_', ' ')}.",
                mechanical_details="Item not in inventory.",
            )

        if item_name == "healing_potion":
            from .mechanics import DieRoll
            heal_roll = DieRoll("2d4+2").roll()
            heal_amount = heal_roll.total
            old_hp = player.hp
            player.hp = min(player.max_hp, player.hp + heal_amount)

            item_entry["qty"] -= 1
            if item_entry["qty"] <= 0:
                player.inventory.remove(item_entry)

            return CombatTurnResult(
                actor_id="player",
                action_type="use_item",
                target_id="player",
                success=True,
                damage_dealt=0,
                narrative_summary=f"You drink the healing potion and recover {heal_amount} HP. ({old_hp} → {player.hp})",
                mechanical_details=f"Healing: {heal_roll} = {heal_amount} HP",
                state_changes={"player_hp": player.hp},
            )

        return CombatTurnResult(
            actor_id="player",
            action_type="use_item",
            target_id=None,
            success=True,
            damage_dealt=0,
            narrative_summary=f"You use the {item_name.replace('_', ' ')}.",
            mechanical_details="Item effect applied.",
        )

    # ------------------------------------------------------------------
    # NPC action resolvers
    # ------------------------------------------------------------------

    def _resolve_npc_attack(self, npc: NPCState, target: PlayerState) -> CombatTurnResult:
        """Simple NPC AI: pick best action and attack the player."""
        if not npc.actions:
            return CombatTurnResult(
                actor_id=npc.npc_id,
                action_type="attack",
                target_id="player",
                success=False,
                damage_dealt=0,
                narrative_summary=f"The {npc.kind} snarls but takes no action.",
                mechanical_details="No actions available.",
            )

        action_data = self._npc_choose_action(npc)

        # Build a weapon_data-compatible dict from the NPC action
        weapon_data = {
            "name": action_data.get("name", "Attack"),
            "damage": action_data.get("damage_die", "1d4"),
            "damage_type": action_data.get("damage_type", "physical"),
            "type": action_data.get("type", "melee_attack"),
            "properties": [],
            "range": action_data.get("range", 5),
        }

        # Difficulty: player_disadvantage → NPC attacks with advantage
        config_mods = self.state.world.config.modifiers
        npc_advantage = config_mods.get("player_disadvantage", False)

        # Dodge condition: NPC attacks with disadvantage
        if "dodging" in (target.conditions or []):
            npc_advantage = False
            npc_disadvantage = True
        else:
            npc_disadvantage = False

        # Override: NPC has a fixed attack bonus in actions list
        # We build a synthetic snapshot with the right attack modifier
        attack_bonus = action_data.get("attack", 2)

        npc_snapshot = EntitySnapshot(
            name=f"{npc.kind} ({npc.npc_id})",
            level=max(1, npc.proficiency_bonus - 1),
            ability_scores=npc.ability_scores.to_dict(),
            proficient_skills=list(npc.skills.keys()),
            proficient_saves=[],
            equipped={"main_hand": npc.equipped[0] if npc.equipped else ""},
            conditions=npc.conditions,
            char_class="npc",
            ac=npc.ac,
            hp=npc.hp,
            max_hp=npc.max_hp,
        )
        target_snapshot = EntitySnapshot(**target.to_snapshot_dict())

        # Use a modified approach: override attack modifier via a custom weapon_data entry
        # that already has the attack bonus built into it
        # We do this by faking a weapon with a large STR score that gives the right bonus
        # Simpler: just roll d20 + attack_bonus directly
        from .mechanics import DieRoll
        atk_roll = DieRoll("1d20", advantage=npc_advantage, disadvantage=npc_disadvantage).roll()
        raw = atk_roll.selected_rolls[0]
        atk_total = raw + attack_bonus

        hit = (raw != 1) and (raw == 20 or atk_total >= target.ac)
        crit = (raw == 20)

        damage = 0
        dmg_detail = ""
        state_changes = {}

        if hit:
            dmg_roll = DieRoll(weapon_data["damage"], crit=crit).roll()
            damage = max(1, dmg_roll.total)
            target.hp = max(0, target.hp - damage)
            state_changes["player_hp"] = target.hp
            dmg_detail = f"Damage: {dmg_roll} = {damage}"

        summary = (
            f"The {npc.kind} attacks you with {action_data.get('name', 'its weapon')}! "
            + (f"[HIT] for {damage} {weapon_data['damage_type']} damage!"
               if hit else "[MISS]!")
        )
        if crit:
            summary = "CRITICAL HIT! " + summary

        # Remove dodge condition after being attacked
        if "dodging" in (target.conditions or []):
            target.conditions.remove("dodging")

        return CombatTurnResult(
            actor_id=npc.npc_id,
            action_type="attack",
            target_id="player",
            success=hit,
            damage_dealt=damage,
            narrative_summary=summary,
            mechanical_details=f"d20={raw} + {attack_bonus} = {atk_total} vs AC {target.ac} → {'HIT' if hit else 'MISS'}. {dmg_detail}",
            state_changes=state_changes,
        )

    def _npc_choose_action(self, npc: NPCState) -> dict:
        """Pick the highest expected damage action from the NPC's action list."""
        if not npc.actions:
            return {}

        def expected_damage(action: dict) -> float:
            die_str = action.get("damage_die", "1d4")
            try:
                from .mechanics import DieRoll
                num, sides, mod = DieRoll.parse_notation(die_str)
                return (num * (sides + 1) / 2) + mod
            except Exception:
                return 2.0

        return max(npc.actions, key=expected_damage)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_target(self, target_hint: Optional[str]) -> Optional[NPCState]:
        """
        Find the best matching hostile NPC for a given target hint.
        Falls back to the first alive hostile NPC if no match.
        """
        hostile = self.state.world.get_hostile_npcs()
        if not hostile:
            return None

        if target_hint:
            # Try to match by kind or npc_id
            hint = target_hint.lower()
            for npc in hostile:
                if hint in npc.kind.lower() or hint in npc.npc_id.lower():
                    return npc

        return hostile[0]  # default to first

    def display_combat_result(self, result: CombatTurnResult):
        """Print a Rich panel for a combat turn result."""
        actor = "You" if result.actor_id == "player" else result.actor_id
        color = "green" if result.actor_id == "player" else "red"
        title = f"[{color}]{actor}[/{color}] — {result.action_type.title()}"

        content = f"{result.narrative_summary}\n[dim]{result.mechanical_details}[/dim]"
        if result.state_changes:
            changes = "  ".join(f"{k}: {v}" for k, v in result.state_changes.items())
            content += f"\n[dim italic]State: {changes}[/dim italic]"

        self.console.print(Panel(content, title=title, border_style=color))
