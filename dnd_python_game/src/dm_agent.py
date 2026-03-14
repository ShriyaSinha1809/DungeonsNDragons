"""
dm_agent.py - LLM-powered Dungeon Master agent.
Uses Groq API (OpenAI-compatible) with retry logic and optional streaming.
"""
import json
import os
import time
from typing import Any, Optional, TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.text import Text

from .config_builder import SessionConfig

if TYPE_CHECKING:
    from .state_manager import PlayerState


class DMAgent:
    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        self.conversation_history: list[dict] = []
        self._client = None
        self._model = "llama-3.3-70b-versatile"  # Groq model
        self._max_history = 20   # keep system + last 19 messages
        self._console = Console()

    def _get_client(self):
        """Lazy-init the Groq client (OpenAI-compatible). Raises RuntimeError if key missing."""
        if self._client is not None:
            return self._client

        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY environment variable not set.\n"
                "Export it with: export GROQ_API_KEY='your-key'"
            )

        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        return self._client

    def _build_persona(
        self,
        custom_rules: str,
        modifiers: dict[str, Any],
        player_state: Optional["PlayerState"] = None,
    ) -> str:
        base_prompt = (
            "You are an expert, dynamic Dungeon Master running a D&D 5e campaign. "
            "You receive the current game state, recent turn history, and the player's action "
            "with any dice roll results. Your job is to vividly describe the outcome, "
            "narrate the world with rich sensory detail, advance the plot, and end with "
            "'What do you do?' Keep responses concise — 3 to 6 sentences unless combat "
            "or dramatic moments call for more. Never break immersion or reference the "
            "game mechanics directly unless it helps the story."
        )

        if custom_rules:
            base_prompt += (
                f"\n\nCRITICAL CUSTOM RULE — always respect this: {custom_rules}"
            )
        else:
            difficulty_flavor = {
                1: "This is a forgiving storytelling experience. Lean into narrative over challenge.",
                2: "This is an easy adventure. Enemies are manageable, setbacks are minor.",
                3: "This is a standard D&D campaign. Balance challenge with story.",
                4: "This is a hard, tactical campaign. Enemies are dangerous and unforgiving.",
            }
            diff = getattr(modifiers, "get", lambda k, d: d)
            # modifiers is a dict
            flavor = ""
            if isinstance(modifiers, dict):
                enemy_mult = modifiers.get("enemy_hp_multiplier", 1.0)
                if enemy_mult < 0.8:
                    flavor = difficulty_flavor[1]
                elif enemy_mult < 1.0:
                    flavor = difficulty_flavor[2]
                elif enemy_mult > 1.1:
                    flavor = difficulty_flavor[4]
                else:
                    flavor = difficulty_flavor[3]
            base_prompt += f"\n\nCAMPAIGN TONE: {flavor}"

        if player_state:
            base_prompt += (
                f"\n\nThe player character is {player_state.name}, "
                f"a {player_state.race.title()} {player_state.char_class.title()} "
                f"(Level {player_state.level}). "
                f"Always address them as {player_state.name} or in second person."
            )

        return base_prompt

    def start_session(
        self,
        config: SessionConfig,
        player_state: Optional["PlayerState"] = None,
    ) -> None:
        """Initialize the DM persona and conversation history."""
        self.system_prompt = self._build_persona(
            config.custom_rules, config.modifiers, player_state
        )
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]

    def generate_response(
        self,
        context_payload: dict[str, Any],
        player_action: str,
        stream: bool = False,
    ) -> str:
        """
        Generate a DM narrative response using OpenAI gpt-4o.
        Retries up to 3 times with exponential backoff on transient errors.
        Trims conversation history to prevent token overflow.
        """
        # Build user message
        # Compact the context to avoid huge token counts
        compact_context = self._compact_context(context_payload)
        user_message = (
            f"GAME STATE:\n{json.dumps(compact_context, indent=2)}"
            f"\n\nPLAYER ACTION: {player_action}"
        )
        self.conversation_history.append({"role": "user", "content": user_message})

        # Trim history: keep system prompt + last (max_history - 1) messages
        if len(self.conversation_history) > self._max_history:
            system_msg = self.conversation_history[0]
            recent = self.conversation_history[-(self._max_history - 1):]
            self.conversation_history = [system_msg] + recent

        response_text = self._call_api_with_retry(stream=stream)

        self.conversation_history.append({"role": "assistant", "content": response_text})
        return response_text

    def _call_api_with_retry(self, stream: bool = False) -> str:
        """Call the OpenAI API with retry logic for transient failures."""
        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package not installed.")

        client = self._get_client()
        max_attempts = 3
        backoff = 1  # seconds

        for attempt in range(max_attempts):
            try:
                if stream:
                    return self._stream_response(client)
                else:
                    response = client.chat.completions.create(
                        model=self._model,
                        messages=self.conversation_history,
                        max_tokens=600,
                        temperature=0.85,
                    )
                    return response.choices[0].message.content

            except openai.RateLimitError:
                if attempt < max_attempts - 1:
                    self._console.print(
                        f"[dim yellow]Rate limit reached. Waiting {backoff}s...[/dim yellow]"
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

            except openai.APIConnectionError:
                if attempt < max_attempts - 1:
                    self._console.print(
                        f"[dim yellow]Connection error. Retrying in {backoff}s...[/dim yellow]"
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

            except openai.APIStatusError as e:
                if e.status_code in (500, 502, 503, 504) and attempt < max_attempts - 1:
                    self._console.print(
                        f"[dim yellow]Server error {e.status_code}. Retrying in {backoff}s...[/dim yellow]"
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

        raise RuntimeError("OpenAI API failed after max retries.")

    def _stream_response(self, client) -> str:
        """Stream the response token by token using Rich Live display."""
        full_text = ""

        with Live(Text(""), refresh_per_second=15, console=self._console) as live:
            stream = client.chat.completions.create(
                model=self._model,
                messages=self.conversation_history,
                max_tokens=600,
                temperature=0.85,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    live.update(Text(full_text))

        return full_text

    def _compact_context(self, context: dict) -> dict:
        """
        Reduce context payload size for token efficiency.
        Keeps essential state, trims verbose nested data.
        """
        player = context.get("player", {})
        compact_player = {
            "name": player.get("name"),
            "class": player.get("char_class"),
            "race": player.get("race"),
            "level": player.get("level"),
            "hp": f"{player.get('hp')}/{player.get('max_hp')}",
            "ac": player.get("ac"),
            "location": player.get("location"),
            "conditions": player.get("conditions"),
            "equipped": player.get("equipped"),
            "gold": player.get("gold"),
            "xp": player.get("xp"),
        }
        if player.get("spell_slots"):
            compact_player["spell_slots"] = player["spell_slots"]
        if player.get("known_spells"):
            compact_player["spells"] = player["known_spells"]

        return {
            "player": compact_player,
            "npcs": context.get("npcs", {}),
            "quests": [
                {"title": q.get("title"), "objectives": q.get("objectives")}
                for q in context.get("quests", [])
            ],
            "scene": context.get("scene", ""),
            "combat": context.get("combat"),
            "recent_history": context.get("history", [])[-3:],
            "difficulty_rules": context.get("difficulty_rules", ""),
        }
