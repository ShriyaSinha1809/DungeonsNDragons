"""
session_store.py — In-memory session registry with disk-based persistence.
Each session holds its own StateManager, DMAgent, CombatManager, etc.
"""
import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.config_builder import SessionConfig
from src.state_manager import StateManager
from src.dm_agent import DMAgent
from src.combat import CombatManager
from src.intent_parser import IntentParser
from src.mechanics import MechanicsEngine


@dataclass
class SessionContainer:
    session_id: str
    config: SessionConfig
    state_manager: StateManager
    dm_agent: DMAgent
    combat_manager: CombatManager
    intent_parser: IntentParser
    mechanics: MechanicsEngine
    status: str = "awaiting_character"   # awaiting_character | active | game_over
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Per-session lock prevents concurrent writes to the same game state
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """
    Thread-safe in-memory registry of active game sessions.
    Delegates disk I/O to StateManager.save_game / load_game.
    """

    def __init__(self, save_dir: Optional[str] = None):
        self._sessions: dict[str, SessionContainer] = {}
        self._save_dir = save_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saves"
        )
        os.makedirs(self._save_dir, exist_ok=True)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create(self, difficulty: int = 3, custom_rules: str = "") -> SessionContainer:
        """Instantiate a new session with all game subsystems initialised."""
        session_id = str(uuid.uuid4())
        config = SessionConfig(difficulty=difficulty, custom_rules=custom_rules or "")

        sm = StateManager(config)
        sm.load_data_files()

        mechanics = MechanicsEngine()
        container = SessionContainer(
            session_id=session_id,
            config=config,
            state_manager=sm,
            dm_agent=DMAgent(),
            combat_manager=CombatManager(sm, mechanics),
            intent_parser=IntentParser(),
            mechanics=mechanics,
        )
        self._sessions[session_id] = container
        return container

    def get(self, session_id: str) -> Optional[SessionContainer]:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def all_ids(self) -> list[str]:
        return list(self._sessions.keys())

    # ── Disk persistence ──────────────────────────────────────────────────────

    def save_to_disk(self, session_id: str, slot: Optional[str] = None) -> str:
        """Save world state to disk. Returns the file path written."""
        container = self._require(session_id)
        path = self._save_path(slot or session_id)
        container.state_manager.save_game(path)
        return path

    def load_from_disk(self, session_id: str, slot: Optional[str] = None) -> bool:
        """Restore world state from disk into a live session."""
        container = self._require(session_id)
        path = self._save_path(slot or session_id)
        if not os.path.exists(path):
            return False
        container.state_manager.load_game(path)
        container.status = "active"
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _save_path(self, slot: str) -> str:
        safe = "".join(c for c in slot if c.isalnum() or c in "-_")
        return os.path.join(self._save_dir, f"{safe}.json")

    def _require(self, session_id: str) -> SessionContainer:
        c = self._sessions.get(session_id)
        if c is None:
            raise KeyError(f"Session '{session_id}' not found.")
        return c
