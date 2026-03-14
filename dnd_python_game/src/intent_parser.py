"""
intent_parser.py - Parses player input to extract D&D intent.
Uses keyword matching + regex target/spell extraction.
"""
import re
from typing import Optional


class IntentParser:
    """
    Parses free-form player input into structured intent dicts.

    Return schema:
    {
        "type": str,               # intent category
        "skill": str | None,       # for skill_check type
        "target": str | None,      # extracted target entity
        "spell_name": str | None,  # for spell type
        "item_name": str | None,   # for use_item type
        "meta_command": str | None, # for meta type
        "intent": str              # original input text
    }
    """

    # Patterns for target extraction — capture a single word target, optional prep before it
    TARGET_PATTERN = re.compile(
        r"(?:attack|strike|hit|shoot|stab|kill|fight|engage|slash|bash)"
        r"(?:\s+(?:at|the|a|an|my))*\s+(?:the\s+|a\s+|an\s+)?(\w+)",
        re.IGNORECASE
    )

    # Pattern for spell name extraction: "cast <spell name>"
    SPELL_PATTERN = re.compile(
        r"cast\s+([a-zA-Z][a-zA-Z\s]{1,30}?)(?:\s+(?:on|at|against)\s+|\s*$)",
        re.IGNORECASE
    )

    # Pattern for item use: "use/drink/consume <item>"
    ITEM_PATTERN = re.compile(
        r"(?:use|drink|consume|apply|eat)\s+(?:a\s+|an\s+|the\s+|my\s+)?([a-zA-Z_\s]+?)(?:\s+on\s+|\s*$)",
        re.IGNORECASE
    )

    def parse(self, player_input: str) -> dict:
        text = player_input.strip().lower()
        result = {
            "type": "narrative",
            "skill": None,
            "target": None,
            "spell_name": None,
            "item_name": None,
            "meta_command": None,
            "intent": player_input,
        }

        # --- META COMMANDS ---
        if any(kw in text for kw in ("check my inventory", "open inventory", "show inventory",
                                      "what do i have", "my items", "my bag")):
            result["type"] = "meta"
            result["meta_command"] = "inventory"
            return result

        if any(kw in text for kw in ("check my stats", "character sheet", "my character",
                                      "show stats", "my stats", "stat sheet")):
            result["type"] = "meta"
            result["meta_command"] = "stats"
            return result

        if any(kw in text for kw in ("quest log", "check quests", "my quests",
                                      "active quests", "show quests")):
            result["type"] = "meta"
            result["meta_command"] = "quests"
            return result

        if any(kw in text for kw in ("save game", "save my game", "quick save")):
            result["type"] = "meta"
            result["meta_command"] = "save"
            return result

        if any(kw in text for kw in ("load game", "load save", "restore game")):
            result["type"] = "meta"
            result["meta_command"] = "load"
            return result

        if text in ("help", "show commands", "what can i do", "commands", "/?"):
            result["type"] = "meta"
            result["meta_command"] = "help"
            return result

        # --- INITIATIVE / COMBAT START ---
        if any(kw in text for kw in ("roll for initiative", "start combat", "draw weapon",
                                      "draw my weapon", "begin combat", "prepare for battle",
                                      "i draw my", "weapons ready")):
            result["type"] = "initiative"
            return result

        # --- COMBAT ACTIONS ---
        if any(kw in text for kw in ("dodge", "take cover", "defend myself", "i dodge",
                                      "defensive stance", "brace myself")):
            result["type"] = "dodge"
            return result

        if any(kw in text for kw in ("dash", "i run", "i dash", "double move", "move twice")):
            result["type"] = "dash"
            return result

        if any(kw in text for kw in ("disengage", "back away safely", "retreat carefully",
                                      "i disengage", "disengage from")):
            result["type"] = "disengage"
            return result

        if re.search(r"\b(help|assist|aid)\s+\w", text):
            result["type"] = "help"
            result["target"] = self._extract_target(player_input)
            return result

        # --- ITEM USE ---
        if any(kw in text for kw in ("drink potion", "use potion", "healing potion",
                                      "consume potion", "quaff", "use a potion", "use my potion")):
            result["type"] = "use_item"
            result["item_name"] = "healing_potion"
            return result

        item_match = self.ITEM_PATTERN.search(player_input)
        if item_match and any(kw in text for kw in ("use ", "drink ", "consume ", "apply ")):
            raw_item = item_match.group(1).strip().lower().replace(" ", "_")
            result["type"] = "use_item"
            result["item_name"] = raw_item
            return result

        # --- SPELL CASTING ---
        if any(kw in text for kw in ("cast ", "i cast", "magic missile", "firebolt",
                                      "fire bolt", "cure wounds", "mage armor",
                                      "burning hands", "ray of frost", "shocking grasp")):
            result["type"] = "spell"
            result["spell_name"] = self._extract_spell_name(player_input)
            result["target"] = self._extract_spell_target(player_input)
            return result

        # --- SKILL CHECKS ---
        if any(kw in text for kw in ("sneak", "hide ", "stealth", "quietly", "in shadow",
                                      "move silently", "creep", "tiptoe", "blend in")):
            result["type"] = "skill_check"
            result["skill"] = "stealth"
            return result

        if any(kw in text for kw in ("look around", "look for", "search the", "examine",
                                      "inspect", "perception", "notice", "survey", "scan", "spot")):
            result["type"] = "skill_check"
            result["skill"] = "perception"
            return result

        if any(kw in text for kw in ("investigate", "check for traps", "look for clues",
                                      "examine closely", "study the", "analyze")):
            result["type"] = "skill_check"
            result["skill"] = "investigation"
            return result

        if any(kw in text for kw in ("climb", "jump", "swim", "strength check",
                                      "force open", "break down", "lift", "push open")):
            result["type"] = "skill_check"
            result["skill"] = "athletics"
            return result

        if any(kw in text for kw in ("persuade", "convince", "negotiate", "reason with",
                                      "appeal to", "make a case")):
            result["type"] = "skill_check"
            result["skill"] = "persuasion"
            return result

        if any(kw in text for kw in ("deceive", "lie ", "bluff", "trick the", "mislead",
                                      "pretend to", "make them think")):
            result["type"] = "skill_check"
            result["skill"] = "deception"
            return result

        if any(kw in text for kw in ("intimidate", "threaten", "scare", "menace", "frighten")):
            result["type"] = "skill_check"
            result["skill"] = "intimidation"
            return result

        if any(kw in text for kw in ("pick the lock", "lockpick", "pick lock",
                                      "thieves tools", "unlock", "jimmy the")):
            result["type"] = "skill_check"
            result["skill"] = "thieves_tools"
            return result

        if any(kw in text for kw in ("read them", "can i tell", "insight check",
                                      "get a read on", "sense their")):
            result["type"] = "skill_check"
            result["skill"] = "insight"
            return result

        if any(kw in text for kw in ("track", "forage", "follow tracks",
                                      "navigate the wilderness", "find food")):
            result["type"] = "skill_check"
            result["skill"] = "survival"
            return result

        # --- ATTACK ACTIONS ---
        attack_keywords = ("attack", "hit ", "strike", "slash", "stab", "shoot",
                           "fire at", "swing", "fight", "kill", "slay", "charge")
        if any(kw in text for kw in attack_keywords):
            result["type"] = "attack"
            result["target"] = self._extract_target(player_input)
            return result

        # --- EXPLORATION / INTERACTION ---
        if any(kw in text for kw in ("go to", "move to", "travel to", "walk to", "enter the",
                                      "approach", "head to", "proceed to", "advance to")):
            result["type"] = "exploration"
            return result

        # Default: pure narrative
        result["type"] = "narrative"
        return result

    def _extract_target(self, text: str) -> Optional[str]:
        """Extract target entity name using regex."""
        m = self.TARGET_PATTERN.search(text)
        if m:
            raw = m.group(1).strip().lower()
            stop_words = {"the", "a", "an", "it", "him", "her", "them", "that"}
            tokens = [t for t in raw.split() if t not in stop_words]
            return "_".join(tokens) if tokens else None
        # Fallback: look for "on/at/against the <target>"
        m2 = re.search(r"(?:on|at|against)\s+(?:the\s+|a\s+)?(\w+)", text, re.IGNORECASE)
        if m2:
            return m2.group(1).lower()
        return None

    def _extract_spell_target(self, text: str) -> Optional[str]:
        """Extract target from 'cast X on Y' patterns."""
        m = re.search(r"(?:on|at|against)\s+(?:the\s+|a\s+)?(\w+)", text, re.IGNORECASE)
        if m:
            return m.group(1).lower()
        return None

    def _extract_spell_name(self, text: str) -> Optional[str]:
        """Extract spell name from 'cast <spell>' patterns."""
        m = self.SPELL_PATTERN.search(text)
        if m:
            raw = m.group(1).strip().lower()
            return raw.replace(" ", "_").rstrip("_")

        # Check for spell names directly in text
        known_spells = [
            ("fire bolt", "firebolt"),
            ("firebolt", "firebolt"),
            ("magic missile", "magic_missile"),
            ("cure wounds", "cure_wounds"),
            ("mage armor", "mage_armor"),
            ("burning hands", "burning_hands"),
            ("ray of frost", "ray_of_frost"),
            ("shocking grasp", "shocking_grasp"),
            ("shield", "shield"),
        ]
        text_lower = text.lower()
        for display, key in known_spells:
            if display in text_lower:
                return key

        return None
