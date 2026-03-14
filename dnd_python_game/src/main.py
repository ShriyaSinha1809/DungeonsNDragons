"""
main.py - Entry point and game loop for the D&D 5e multi-agent game.

Run with:
    cd dnd_python_game
    python -m src.main

Requires:
    export OPENAI_API_KEY="your-key"
    pip install openai pyyaml rich
"""
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich import box

from .config_builder import display_welcome_menu
from .state_manager import StateManager
from .dm_agent import DMAgent
from .intent_parser import IntentParser
from .mechanics import MechanicsEngine
from .combat import CombatManager
from .character_builder import CharacterBuilder

console = Console()
SAVE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "savegame.json")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    console.print(Panel.fit(
        "[bold yellow]⚔  DUNGEONS & DRAGONS 5e  ⚔[/bold yellow]\n"
        "[dim]A Multi-Agent AI Storytelling Experience[/dim]",
        border_style="yellow",
    ))

    # --- PHASE 1: Difficulty & Config ---
    config = display_welcome_menu()

    console.print("\n[dim]Initializing session...[/dim]")

    # --- PHASE 2: Module Setup ---
    state_manager = StateManager(config)
    state_manager.load_data_files()

    mechanics = MechanicsEngine()
    combat_manager = CombatManager(state_manager, mechanics)
    intent_parser = IntentParser()
    dm = DMAgent()

    # --- PHASE 3: Character Creation or Load ---
    if _prompt_load_save():
        try:
            state_manager.load_game(SAVE_FILE)
            player = state_manager.world.player
            console.print(f"[green]✓ Loaded save: {player.name} (Level {player.level})[/green]\n")
        except Exception as e:
            console.print(f"[red]Failed to load save: {e}. Starting fresh.[/red]")
            state_manager.world.player = None

    if not state_manager.world.player:
        builder = CharacterBuilder(state_manager)
        player = builder.build()
        state_manager.world.player = player
        state_manager.setup_default_quest()
        # Spawn starting NPCs
        state_manager.spawn_npc("goblin", "goblin_1", location="Goblin Cave — Entrance")
        state_manager.spawn_npc("goblin", "goblin_2", location="Goblin Cave — Entrance")

    player = state_manager.world.player

    # --- PHASE 4: Start DM Session ---
    dm.start_session(config, player)

    # Generate opening narrative
    console.print("\n[dim]The Dungeon Master sets the scene...[/dim]\n")
    opening_payload = state_manager.build_context_payload()
    try:
        opening = dm.generate_response(
            opening_payload,
            "Begin the adventure. Set an atmospheric opening scene befitting the character's background.",
            stream=True,
        )
        console.print(Panel(opening, title="[bold yellow]⚔ Dungeon Master[/bold yellow]",
                            border_style="yellow"))
    except Exception as e:
        console.print(Panel(
            f"[The DM clears their throat...]\n\n"
            f"You are {player.name}, a {player.race} {player.char_class} in a world of danger and wonder. "
            f"A goblin cave looms nearby — the village elder has asked you to deal with them.\n\n"
            f"[dim](Note: OpenAI API error: {e})[/dim]",
            title="[bold yellow]⚔ Dungeon Master[/bold yellow]",
            border_style="yellow"
        ))

    console.print(Rule("[dim]Type your action below. 'help' for commands, 'quit' to exit.[/dim]"))

    # --- PHASE 5: The Game Loop ---
    while True:
        try:
            player_input = Prompt.ask("\n[bold green]>[/bold green]").strip()

            if not player_input:
                continue

            if player_input.lower() in ("quit", "exit", "q"):
                _handle_quit(state_manager)
                break

            parsed = intent_parser.parse(player_input)

            # --- META BRANCH ---
            if parsed["type"] == "meta":
                _handle_meta_command(parsed, state_manager, dm)
                continue

            # --- TRACK mechanic result for DM context ---
            mechanic_result = ""

            # --- COMBAT INITIATION ---
            if parsed["type"] == "initiative" or (
                parsed["type"] == "attack" and not combat_manager.is_in_combat()
                and state_manager.world.get_hostile_npcs()
            ):
                hostile_ids = [npc.npc_id for npc in state_manager.world.get_hostile_npcs()]
                if hostile_ids:
                    combat_manager.initiate_combat(hostile_ids)
                    mechanic_result = "Combat initiated! Roll for initiative — order determined."
                else:
                    console.print("[yellow]There are no hostile enemies nearby.[/yellow]")

            # --- COMBAT BRANCH ---
            if combat_manager.is_in_combat():
                turn_result = combat_manager.process_player_turn(parsed)
                combat_manager.display_combat_result(turn_result)
                mechanic_result = turn_result.mechanical_details
                state_manager.world.log_action(player_input, turn_result.narrative_summary)

                end_state = combat_manager.check_combat_end()

                if end_state == "player_defeat":
                    console.print(Panel(
                        "[bold red]You have fallen in battle. Your adventure ends here...[/bold red]",
                        border_style="red"
                    ))
                    _dm_narrate(dm, state_manager, f"The player has been defeated. {turn_result.narrative_summary}", stream=True)
                    break

                elif end_state == "player_unconscious":
                    _handle_death_saves(state_manager, mechanics, dm, combat_manager)
                    continue

                elif end_state == "player_victory":
                    post = combat_manager.resolve_post_combat()
                    _display_post_combat(post)
                    mechanic_result += f" | Victory! +{post.xp_gained} XP"
                    if post.leveled_up:
                        console.print(Panel(
                            f"[bold yellow]⬆  LEVEL UP! You are now level {post.new_level}![/bold yellow]",
                            border_style="yellow"
                        ))

                else:
                    # NPCs take their turns
                    npc_results = combat_manager.process_npc_turns()
                    for r in npc_results:
                        combat_manager.display_combat_result(r)
                        state_manager.world.log_action(f"{r.actor_id} attacks", r.narrative_summary)

                    combat_manager.advance_turn()

                    # Check again after NPC turns
                    end_state = combat_manager.check_combat_end()
                    if end_state == "player_defeat":
                        console.print(Panel(
                            "[bold red]You have been slain. Your story ends...[/bold red]",
                            border_style="red"
                        ))
                        _dm_narrate(dm, state_manager, "The player has been defeated by enemies. Narrate their fall dramatically.", stream=True)
                        break
                    elif end_state == "player_unconscious":
                        _handle_death_saves(state_manager, mechanics, dm, combat_manager)
                        continue

            # --- EXPLORATION / SKILL BRANCH ---
            elif parsed["type"] in ("skill_check", "exploration", "narrative",
                                    "dodge", "dash", "disengage", "use_item"):
                if parsed["type"] == "skill_check":
                    mechanic_result = state_manager.resolve_mechanic(player_input, parsed)
                elif parsed["type"] == "use_item":
                    mechanic_result = _resolve_out_of_combat_item(parsed, state_manager)
                else:
                    mechanic_result = "Action requires narrative resolution."

                state_manager.world.log_action(player_input, mechanic_result)

            # --- DM NARRATION (all non-meta branches converge here) ---
            action_log = _build_action_log(parsed, player_input, mechanic_result)
            _dm_narrate(dm, state_manager, action_log, stream=True)

        except KeyboardInterrupt:
            console.print("\n")
            _handle_quit(state_manager)
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            import traceback
            traceback.print_exc(file=sys.stderr)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _dm_narrate(dm: DMAgent, state_manager: StateManager, action_log: str, stream: bool = False):
    """Build context, call DM, and display the response."""
    context = state_manager.build_context_payload()
    console.print("\n[dim italic]Dungeon Master is narrating...[/dim italic]")
    try:
        response = dm.generate_response(context, action_log, stream=stream)
        console.print(Panel(
            response,
            title="[bold yellow]⚔ Dungeon Master[/bold yellow]",
            border_style="yellow"
        ))
    except Exception as e:
        console.print(f"[red]DM Agent error: {e}[/red]")


def _handle_meta_command(parsed: dict, state_manager: StateManager, dm: DMAgent):
    cmd = parsed.get("meta_command")
    player = state_manager.world.player

    if cmd == "inventory":
        _show_inventory(player)

    elif cmd == "stats":
        _show_stats(player)

    elif cmd == "quests":
        _show_quests(state_manager.world.active_quests)

    elif cmd == "save":
        try:
            state_manager.save_game(SAVE_FILE)
            console.print(f"[green]✓ Game saved to {SAVE_FILE}[/green]")
        except Exception as e:
            console.print(f"[red]Save failed: {e}[/red]")

    elif cmd == "load":
        try:
            state_manager.load_game(SAVE_FILE)
            console.print(f"[green]✓ Game loaded.[/green]")
        except Exception as e:
            console.print(f"[red]Load failed: {e}[/red]")

    elif cmd == "help":
        _show_help()


def _show_inventory(player):
    if not player:
        return
    table = Table(title=f"[bold]{player.name}'s Inventory[/bold]",
                  box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("Item", style="white")
    table.add_column("Qty", style="yellow", justify="right")
    table.add_column("Slot", style="dim")

    # Equipped items
    for slot, item in player.equipped.items():
        table.add_row(item.replace("_", " ").title(), "—", f"[cyan]{slot}[/cyan]")

    # Inventory items
    for item in player.inventory:
        table.add_row(
            item.get("type", "?").replace("_", " ").title(),
            str(item.get("qty", 1)),
            "bag"
        )

    if player.spell_slots:
        slots_str = "  ".join(f"L{k}: {v}" for k, v in player.spell_slots.items())
        table.add_row(f"[magenta]Spell Slots: {slots_str}[/magenta]", "", "")

    table.add_row(f"[yellow]{player.gold} gp[/yellow]", "", "purse")
    console.print(table)


def _show_stats(player):
    if not player:
        return
    from .mechanics import MechanicsEngine
    engine = MechanicsEngine()
    ABILITY_NAMES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
                     "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}

    table = Table(
        title=f"[bold]{player.name}[/bold] — {player.race.title()} {player.char_class.title()} Lv.{player.level}",
        box=box.DOUBLE_EDGE, show_header=False, padding=(0, 1)
    )
    table.add_column("Stat", style="bold cyan", min_width=18)
    table.add_column("Value", style="white")

    table.add_row("HP", f"{player.hp} / {player.max_hp}")
    table.add_row("Armor Class", str(player.ac))
    table.add_row("XP", f"{player.xp}")
    table.add_row("Gold", f"{player.gold} gp")
    table.add_row("Location", player.location)
    if player.conditions:
        table.add_row("Conditions", ", ".join(player.conditions))
    table.add_row("", "")

    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        score = getattr(player.ability_scores, ab)
        mod = engine.ability_modifier(score)
        table.add_row(ABILITY_NAMES[ab], f"{score:2d}  ({mod:+d})")

    table.add_row("", "")
    table.add_row("Proficient Skills", ", ".join(player.proficient_skills) or "—")
    table.add_row("Saving Throws", ", ".join(player.proficient_saves) or "—")
    console.print(table)


def _show_quests(quests):
    if not quests:
        console.print("[dim]No active quests.[/dim]")
        return
    for quest in quests:
        status = "[green]COMPLETE[/green]" if quest.completed else "[yellow]IN PROGRESS[/yellow]"
        table = Table(title=f"{quest.title}  {status}", box=box.SIMPLE_HEAVY,
                      show_header=False)
        table.add_column("", style="white")
        table.add_row(quest.description)
        for obj in quest.objectives:
            check = "[green]✓[/green]" if obj.get("completed") else "[red]○[/red]"
            table.add_row(f"  {check} {obj.get('description', '')}")
        console.print(table)


def _show_help():
    table = Table(title="Commands", box=box.SIMPLE_HEAVY, show_header=True,
                  header_style="bold magenta")
    table.add_column("Command", style="cyan", min_width=28)
    table.add_column("Effect", style="white")
    rows = [
        ("check my inventory / my items", "Show inventory and equipped items"),
        ("check my stats / character sheet", "Show character stats and abilities"),
        ("quest log / check quests", "Show active quests"),
        ("save game", "Save current progress"),
        ("load game", "Load saved progress"),
        ("roll for initiative / start combat", "Begin combat with nearby enemies"),
        ("attack the [enemy]", "Make a melee or ranged attack"),
        ("cast [spell] on [target]", "Cast a known spell"),
        ("dodge / dash / disengage", "Combat actions"),
        ("use healing potion", "Consume a healing potion"),
        ("stealth / sneak", "Attempt a stealth check"),
        ("look around / search", "Perception or investigation check"),
        ("quit / exit", "Save and exit the game"),
    ]
    for cmd, effect in rows:
        table.add_row(cmd, effect)
    console.print(table)


def _display_post_combat(post):
    lines = [f"[bold green]Victory![/bold green]  +{post.xp_gained} XP"]
    if post.loot:
        loot_str = ", ".join(
            f"{i.get('qty', 1)}x {i.get('type', '?').replace('_', ' ')}"
            for i in post.loot
        )
        lines.append(f"Loot: {loot_str}")
    if post.leveled_up:
        lines.append(f"[bold yellow]⬆ LEVEL UP — now level {post.new_level}![/bold yellow]")
    console.print(Panel("\n".join(lines), title="Post-Combat", border_style="green"))


def _handle_death_saves(state_manager: StateManager, mechanics: MechanicsEngine,
                        dm: DMAgent, combat_manager: CombatManager):
    """Manage the death saving throw loop until stable or dead."""
    player = state_manager.world.player
    console.print(Panel(
        "[bold red]You are unconscious and making death saving throws![/bold red]\n"
        f"Successes: {player.death_saves['successes']}  |  "
        f"Failures: {player.death_saves['failures']}",
        border_style="red"
    ))

    from .mechanics import EntitySnapshot
    snapshot = EntitySnapshot(**player.to_snapshot_dict())
    result = mechanics.resolve_death_save(snapshot)

    console.print(f"[dim]{result.mechanical_summary()}[/dim]")

    if result.nat_20:
        player.hp = 1
        player.death_saves = {"successes": 0, "failures": 0}
        console.print("[bold green]Miraculous recovery! You regain 1 HP and consciousness![/bold green]")
    elif result.nat_1:
        player.death_saves["failures"] = min(3, player.death_saves.get("failures", 0) + 2)
    elif result.success:
        player.death_saves["successes"] = player.death_saves.get("successes", 0) + 1
    else:
        player.death_saves["failures"] = player.death_saves.get("failures", 0) + 1

    if player.death_saves.get("successes", 0) >= 3:
        player.death_saves = {"successes": 0, "failures": 0}
        console.print("[bold green]You stabilize and regain consciousness with 1 HP![/bold green]")
        player.hp = 1
    elif player.death_saves.get("failures", 0) >= 3:
        console.print("[bold red]You have died. Three death save failures.[/bold red]")


def _resolve_out_of_combat_item(parsed: dict, state_manager: StateManager) -> str:
    """Use an item outside of combat (e.g., drink a potion while exploring)."""
    player = state_manager.world.player
    item_name = parsed.get("item_name", "healing_potion")

    item_entry = next(
        (i for i in player.inventory if i.get("type") == item_name and i.get("qty", 0) > 0),
        None
    )
    if not item_entry:
        return f"You don't have any {item_name.replace('_', ' ')}."

    if item_name == "healing_potion":
        from .mechanics import DieRoll
        heal = DieRoll("2d4+2").roll()
        old_hp = player.hp
        player.hp = min(player.max_hp, player.hp + heal.total)
        item_entry["qty"] -= 1
        if item_entry["qty"] <= 0:
            player.inventory.remove(item_entry)
        return f"Drank healing potion. Healed {heal.total} HP. ({old_hp} → {player.hp})"

    return f"Used {item_name.replace('_', ' ')}."


def _build_action_log(parsed: dict, raw_input: str, mechanic_result: str) -> str:
    """Build the action description string passed to the DM Agent."""
    intent_type = parsed.get("type", "narrative")
    parts = [f"Player Intent: [{intent_type}]", f"Input: '{raw_input}'"]
    if mechanic_result and mechanic_result != "Action requires narrative resolution.":
        parts.append(f"System Result: {mechanic_result}")
    if parsed.get("target"):
        parts.append(f"Target: {parsed['target']}")
    if parsed.get("spell_name"):
        parts.append(f"Spell: {parsed['spell_name']}")
    return " | ".join(parts)


def _prompt_load_save() -> bool:
    """Check for a save file and ask if the user wants to load it."""
    if os.path.exists(SAVE_FILE):
        choice = Prompt.ask(
            "[bold]Save file found. Load it?[/bold]",
            choices=["y", "n"],
            default="n"
        )
        return choice.lower() == "y"
    return False


def _handle_quit(state_manager: StateManager):
    """Prompt save on exit."""
    choice = Prompt.ask(
        "[bold]Save before quitting?[/bold]",
        choices=["y", "n"],
        default="y"
    )
    if choice.lower() == "y":
        try:
            state_manager.save_game(SAVE_FILE)
            console.print(f"[green]Saved to {SAVE_FILE}[/green]")
        except Exception as e:
            console.print(f"[red]Save failed: {e}[/red]")
    console.print("\n[bold yellow]Farewell, adventurer! May your dice roll true.[/bold yellow]\n")


if __name__ == "__main__":
    main()
