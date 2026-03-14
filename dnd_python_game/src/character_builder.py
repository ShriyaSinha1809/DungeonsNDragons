"""
character_builder.py - Interactive terminal character creation using Rich.
Returns a fully populated PlayerState.
"""
import os
import random

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from rich.rule import Rule
from rich import box

from .state_manager import PlayerState, AbilityScores, StateManager
from .mechanics import DieRoll, MechanicsEngine

console = Console()

# Built-in backgrounds (no YAML needed)
BACKGROUNDS = {
    "1": {
        "name": "Soldier",
        "skills": ["athletics", "intimidation"],
        "description": "You served in a military unit. Trained in combat and tactics.",
        "starting_gold": 10,
    },
    "2": {
        "name": "Criminal",
        "skills": ["stealth", "deception"],
        "description": "You operated outside the law. Expert at avoiding notice.",
        "starting_gold": 15,
    },
    "3": {
        "name": "Scholar",
        "skills": ["arcana", "history"],
        "description": "You pursued academic knowledge. Well-versed in lore and magic.",
        "starting_gold": 10,
    },
    "4": {
        "name": "Noble",
        "skills": ["history", "persuasion"],
        "description": "You come from a family of wealth and influence.",
        "starting_gold": 25,
    },
}

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]
ABILITY_NAMES = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}


class CharacterBuilder:
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.engine = MechanicsEngine()

    def build(self) -> PlayerState:
        """Orchestrate full interactive character creation."""
        console.print(Panel.fit(
            "[bold yellow]⚔  CHARACTER CREATION  ⚔[/bold yellow]",
            border_style="yellow"
        ))

        while True:
            name = self._prompt_name()
            race_name, race_data = self._select_race()
            subrace_data = self._select_subrace(race_name, race_data)
            class_name, class_data = self._select_class()
            background_data = self._select_background()
            ability_scores = self._assign_ability_scores(race_data, subrace_data)
            skills = self._select_skills(class_data, background_data["skills"])
            equipped, inventory = self._select_starting_equipment(class_name, class_data)
            known_spells, spell_slots, cantrips = self._setup_spells(class_name, class_data)

            con_mod = self.engine.ability_modifier(ability_scores.con)
            dex_mod = self.engine.ability_modifier(ability_scores.dex)
            max_hp = self._calculate_hp(class_data, con_mod)
            ac = self._calculate_ac(equipped, dex_mod)

            # Saves from class
            proficient_saves = class_data.get("saving_throw_proficiency", [])

            player = PlayerState(
                name=name,
                char_class=class_name,
                race=race_name,
                level=1,
                hp=max_hp,
                max_hp=max_hp,
                ac=ac,
                ability_scores=ability_scores,
                location="Tavern — The Tipsy Flagon",
                proficient_skills=skills,
                proficient_saves=proficient_saves,
                equipped=equipped,
                inventory=inventory,
                spell_slots=spell_slots,
                known_spells=known_spells + cantrips,
                gold=background_data.get("starting_gold", 10),
            )

            confirmed = self._show_character_summary(player)
            if confirmed:
                console.print(f"\n[bold green]Character '{name}' created![/bold green]\n")
                return player

    # ------------------------------------------------------------------
    # Individual steps
    # ------------------------------------------------------------------

    def _prompt_name(self) -> str:
        console.print(Rule("[bold]Step 1: Name Your Hero[/bold]"))
        name = Prompt.ask("[bold cyan]Enter your character's name[/bold cyan]",
                          default="Aric Stormveil")
        return name.strip() or "Hero"

    def _select_race(self) -> tuple[str, dict]:
        console.print(Rule("[bold]Step 2: Choose Your Race[/bold]"))
        races = {
            "1": "human",
            "2": "elf",
            "3": "halfling",
            "4": "dwarf",
        }
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Race", style="bold")
        table.add_column("Key Bonus", style="cyan")
        table.add_column("Speed", style="green")

        race_info = [
            ("1", "Human", "+1 to all ability scores", "30 ft"),
            ("2", "Elf", "+2 DEX, Darkvision 60ft", "30 ft"),
            ("3", "Halfling", "+2 DEX, Lucky trait", "25 ft"),
            ("4", "Dwarf", "+2 CON, Darkvision 60ft, Poison Resistance", "25 ft"),
        ]
        for row in race_info:
            table.add_row(*row)
        console.print(table)

        choice = Prompt.ask("Choose a race", choices=["1", "2", "3", "4"])
        race_key = races[choice]
        race_data = self.state_manager.get_race_data(race_key)
        console.print(f"[green]✓ Selected: {race_data.get('name', race_key.title())}[/green]\n")
        return race_key, race_data

    def _select_subrace(self, race_name: str, race_data: dict) -> dict:
        """If race has subraces, prompt selection. Returns subrace data or {}."""
        subraces = race_data.get("subrace", {})
        if not subraces:
            return {}

        console.print(f"[bold]Choose your {race_name.title()} subrace:[/bold]")
        choices = list(subraces.items())
        for i, (key, sr) in enumerate(choices, 1):
            desc = sr.get("description", "")
            console.print(f"  [cyan]{i}.[/cyan] [bold]{sr.get('name', key)}[/bold] — {desc[:80]}")

        valid = [str(i) for i in range(1, len(choices) + 1)]
        choice = Prompt.ask("Choose subrace", choices=valid)
        _, subrace_data = choices[int(choice) - 1]
        console.print(f"[green]✓ Selected: {subrace_data.get('name', '')}[/green]\n")
        return subrace_data

    def _select_class(self) -> tuple[str, dict]:
        console.print(Rule("[bold]Step 3: Choose Your Class[/bold]"))
        classes = {"1": "fighter", "2": "rogue", "3": "wizard"}
        class_info = [
            ("1", "Fighter", "1d10", "Martial warrior, master of weapons and armor"),
            ("2", "Rogue", "1d8", "Stealthy trickster, expert in skills and sneak attacks"),
            ("3", "Wizard", "1d6", "Arcane spellcaster, wielder of powerful magic"),
        ]
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Class", style="bold")
        table.add_column("Hit Die", style="cyan")
        table.add_column("Description", style="white")
        for row in class_info:
            table.add_row(*row)
        console.print(table)

        choice = Prompt.ask("Choose a class", choices=["1", "2", "3"])
        class_key = classes[choice]
        class_data = self.state_manager.get_class_data(class_key)
        console.print(f"[green]✓ Selected: {class_key.title()}[/green]\n")
        return class_key, class_data

    def _select_background(self) -> dict:
        console.print(Rule("[bold]Step 4: Choose Your Background[/bold]"))
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Background", style="bold")
        table.add_column("Skills", style="cyan")
        table.add_column("Description", style="white")
        for key, bg in BACKGROUNDS.items():
            table.add_row(key, bg["name"], ", ".join(bg["skills"]), bg["description"])
        console.print(table)

        choice = Prompt.ask("Choose a background", choices=list(BACKGROUNDS.keys()))
        bg = BACKGROUNDS[choice]
        console.print(f"[green]✓ Selected: {bg['name']}[/green]\n")
        return bg

    def _assign_ability_scores(self, race_data: dict, subrace_data: dict) -> AbilityScores:
        console.print(Rule("[bold]Step 5: Assign Ability Scores[/bold]"))
        console.print("  [cyan]1.[/cyan] Standard Array [15, 14, 13, 12, 10, 8]")
        console.print("  [cyan]2.[/cyan] Roll 4d6 drop lowest (6 arrays to choose from)")
        method = Prompt.ask("Choose method", choices=["1", "2"])

        if method == "1":
            available = list(STANDARD_ARRAY)
        else:
            # Roll 6 arrays, user picks one
            arrays = []
            for _ in range(6):
                rolls = sorted(
                    [sum(sorted([random.randint(1, 6) for _ in range(4)])[1:]) for _ in range(6)],
                    reverse=True
                )
                arrays.append(rolls)

            console.print("\n[bold]Rolled arrays:[/bold]")
            for i, arr in enumerate(arrays, 1):
                total = sum(arr)
                mods = [f"{self.engine.ability_modifier(s):+d}" for s in arr]
                console.print(f"  {i}. {arr}  (mods: {mods}, total: {total})")

            choice = IntPrompt.ask("Choose array", default=1)
            choice = max(1, min(len(arrays), choice))
            available = arrays[choice - 1]

        # Assign each score to an ability
        console.print("\n[bold]Assign scores to abilities.[/bold]")
        console.print(f"Available scores: [yellow]{available}[/yellow]")
        assigned = {}
        remaining = list(available)

        for ability in ABILITIES:
            while True:
                console.print(f"  Remaining: [yellow]{remaining}[/yellow]")
                try:
                    val = IntPrompt.ask(
                        f"  Assign score to [bold]{ABILITY_NAMES[ability]}[/bold] ({ability.upper()})"
                    )
                    if val in remaining:
                        assigned[ability] = val
                        remaining.remove(val)
                        break
                    else:
                        console.print(f"  [red]{val} is not in the remaining scores.[/red]")
                except (ValueError, KeyboardInterrupt):
                    console.print("[red]Invalid input.[/red]")

        # Apply racial bonuses
        race_bonus = race_data.get("attribute_bonus", {})
        subrace_bonus = subrace_data.get("attribute_bonus", {})
        for ab, bonus in {**race_bonus, **subrace_bonus}.items():
            assigned[ab] = assigned.get(ab, 10) + bonus

        scores = AbilityScores(**{k: assigned.get(k, 10) for k in ABILITIES})

        # Show final scores
        console.print("\n[bold]Final Ability Scores (after racial bonuses):[/bold]")
        row_vals = [f"{ABILITY_NAMES[a]}: {getattr(scores, a)} ({self.engine.ability_modifier(getattr(scores, a)):+d})"
                    for a in ABILITIES]
        console.print("  " + "  |  ".join(row_vals[:3]))
        console.print("  " + "  |  ".join(row_vals[3:]))
        console.print()

        return scores

    def _select_skills(self, class_data: dict, bg_skills: list[str]) -> list[str]:
        console.print(Rule("[bold]Step 6: Choose Skills[/bold]"))
        available = [s for s in class_data.get("available_skills", []) if s not in bg_skills]
        num_choices = class_data.get("available_skills_choices", 2)

        console.print(f"[dim]Background grants:[/dim] [cyan]{', '.join(bg_skills)}[/cyan]")
        console.print(f"[dim]Choose {num_choices} additional skill(s) from:[/dim]")

        for i, skill in enumerate(available, 1):
            console.print(f"  [cyan]{i:2}.[/cyan] {skill.replace('_', ' ').title()}")

        chosen = list(bg_skills)
        for pick_num in range(num_choices):
            while True:
                try:
                    choice = IntPrompt.ask(f"Pick skill {pick_num + 1}")
                    if 1 <= choice <= len(available):
                        skill = available[choice - 1]
                        if skill not in chosen:
                            chosen.append(skill)
                            console.print(f"[green]✓ Added: {skill}[/green]")
                            break
                        else:
                            console.print("[red]Already chosen.[/red]")
                    else:
                        console.print(f"[red]Enter a number between 1 and {len(available)}.[/red]")
                except (ValueError, KeyboardInterrupt):
                    console.print("[red]Invalid input.[/red]")

        return chosen

    def _select_starting_equipment(self, class_name: str, class_data: dict) -> tuple[dict, list]:
        """Returns (equipped_dict, inventory_list) based on class starting equipment."""
        starting = class_data.get("starting_equipment", [])
        equipped = {}
        inventory = [{"type": "healing_potion", "qty": 1}]  # everyone starts with 1 potion

        # Map items to equipment slots
        armor_types = {"chain_mail", "leather_armor", "scale_mail", "chain_shirt",
                       "padded", "studded_leather", "plate_armor", "hide_armor"}
        shield_items = {"shield"}
        off_hand_set = False
        main_hand_set = False

        for item in starting:
            item_lower = item.lower()
            if item_lower in armor_types:
                equipped["armor"] = item_lower
            elif item_lower in shield_items:
                equipped["off_hand"] = item_lower
                off_hand_set = True
            elif item_lower in ("thieves_tools", "component_pouch", "arcane_focus"):
                equipped["utility"] = item_lower
            elif not main_hand_set:
                equipped["main_hand"] = item_lower
                main_hand_set = True
            elif not off_hand_set:
                # Second weapon goes to inventory
                inventory.append({"type": item_lower, "qty": 1})
            else:
                inventory.append({"type": item_lower, "qty": 1})

        # Wizards start with basic component pouch, no armor → AC = 10 + DEX mod
        return equipped, inventory

    def _setup_spells(self, class_name: str, class_data: dict) -> tuple[list, dict, list]:
        """Returns (known_spells, spell_slots, cantrips)."""
        if class_name.lower() != "wizard":
            return [], {}, []

        cantrips = class_data.get("default_cantrips", ["firebolt", "ray_of_frost", "shocking_grasp"])
        spells = class_data.get("default_spells", ["magic_missile", "mage_armor"])
        slots = {"1": class_data.get("spell_slots_by_level", {}).get(1, {}).get(1, 2)}

        console.print(Rule("[bold]Wizard Spells[/bold]"))
        console.print(f"[dim]Cantrips:[/dim] [cyan]{', '.join(cantrips)}[/cyan]")
        console.print(f"[dim]Known 1st-level spells:[/dim] [cyan]{', '.join(spells)}[/cyan]")
        console.print(f"[dim]Spell slots (level 1):[/dim] [cyan]{slots.get('1', 2)}[/cyan]\n")

        return spells, slots, cantrips

    def _calculate_hp(self, class_data: dict, con_mod: int) -> int:
        """Level 1 HP: maximum hit die value + CON modifier."""
        hit_die_sides = class_data.get("hit_die_sides", 8)
        return max(1, hit_die_sides + con_mod)

    def _calculate_ac(self, equipped: dict, dex_mod: int) -> int:
        """Calculate AC from equipped armor."""
        armor_key = equipped.get("armor", "")
        shield = equipped.get("off_hand", "") == "shield"

        if not armor_key:
            # Unarmored: 10 + DEX mod
            base_ac = 10 + dex_mod
        else:
            armor_data = self.state_manager.get_armor_data(armor_key)
            base_ac = armor_data.get("ac", 10)
            mod_cap = armor_data.get("dex_mod_cap")
            if mod_cap is None:
                base_ac += dex_mod
            elif mod_cap == 0:
                pass  # heavy armor, no DEX bonus
            else:
                base_ac += min(dex_mod, mod_cap)

        if shield:
            base_ac += 2

        return base_ac

    def _show_character_summary(self, player: PlayerState) -> bool:
        """Display a Rich table summary and ask for confirmation."""
        console.print(Rule("[bold yellow]Character Summary[/bold yellow]"))

        table = Table(title=f"[bold]{player.name}[/bold] — {player.race.title()} {player.char_class.title()}",
                      box=box.DOUBLE_EDGE, show_header=False, padding=(0, 1))
        table.add_column("Attribute", style="bold cyan", min_width=20)
        table.add_column("Value", style="white")

        table.add_row("Level", str(player.level))
        table.add_row("HP", f"{player.hp} / {player.max_hp}")
        table.add_row("Armor Class", str(player.ac))
        table.add_row("XP", str(player.xp))
        table.add_row("Gold", f"{player.gold} gp")
        table.add_row("", "")

        mods = {a: self.engine.ability_modifier(getattr(player.ability_scores, a)) for a in ABILITIES}
        for a in ABILITIES:
            val = getattr(player.ability_scores, a)
            mod = mods[a]
            table.add_row(ABILITY_NAMES[a], f"{val:2d}  ({mod:+d})")

        table.add_row("", "")
        table.add_row("Skills", ", ".join(player.proficient_skills) or "—")
        table.add_row("Saves", ", ".join(player.proficient_saves) or "—")

        eq_str = ", ".join(f"{slot}: {item}" for slot, item in player.equipped.items())
        table.add_row("Equipped", eq_str or "—")

        inv_str = ", ".join(
            f"{i.get('type', '?')} x{i.get('qty', 1)}" for i in player.inventory
        )
        table.add_row("Inventory", inv_str or "—")

        if player.known_spells:
            table.add_row("Spells", ", ".join(player.known_spells))
        if player.spell_slots:
            slots_str = "  ".join(f"L{k}:{v}" for k, v in player.spell_slots.items())
            table.add_row("Spell Slots", slots_str)

        console.print(table)

        confirm = Prompt.ask("\n[bold]Confirm this character?[/bold]", choices=["y", "n"], default="y")
        return confirm.lower() == "y"
