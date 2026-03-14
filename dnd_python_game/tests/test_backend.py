"""
test_backend.py — Integration tests for the FastAPI backend.

All tests mock DMAgent.generate_response to avoid real Groq API calls.
Run with:
    cd dnd_python_game
    pytest tests/test_backend.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app import create_app
from src.dm_agent import DMAgent


# ── Fixtures ───────────────────────────────────────────────────────────────────

DM_CANNED = "The dungeon echoes with your footsteps. A goblin snarls ahead. What do you do?"

@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_dm():
    """Patch DMAgent.generate_response to return a canned string instantly."""
    with patch.object(DMAgent, "generate_response", return_value=DM_CANNED) as m:
        yield m


def _char_body(name="Testero", char_class="fighter", race="human") -> dict:
    """Build a minimal valid SessionCreateRequest body."""
    return {
        "difficulty": 3,
        "character": {
            "name": name,
            "race": race,
            "char_class": char_class,
            "background": "soldier",
            "ability_assignment": {
                "str": 15, "dex": 12, "con": 14,
                "int": 10, "wis": 10, "cha": 8,
            },
            "skill_choices": ["athletics", "perception"],
        },
    }


# ── Health ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ── Session lifecycle ──────────────────────────────────────────────────────────

class TestSessionLifecycle:
    def test_create_session_returns_201(self, client):
        r = client.post("/api/sessions", json=_char_body())
        assert r.status_code == 201

    def test_create_session_response_has_session_id(self, client):
        r = client.post("/api/sessions", json=_char_body())
        data = r.json()
        assert "session_id" in data
        assert len(data["session_id"]) == 36  # UUID4

    def test_create_session_status_active(self, client):
        r = client.post("/api/sessions", json=_char_body())
        assert r.json()["status"] == "active"

    def test_create_session_returns_player_name(self, client):
        r = client.post("/api/sessions", json=_char_body(name="Gandalf"))
        assert r.json()["player_name"] == "Gandalf"

    def test_get_session_returns_200(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}")
        assert r.status_code == 200

    def test_get_nonexistent_session_returns_404(self, client):
        r = client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_list_sessions_returns_list(self, client):
        client.post("/api/sessions", json=_char_body())
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_delete_session_returns_204(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.delete(f"/api/sessions/{sid}")
        assert r.status_code == 204

    def test_delete_then_get_returns_404(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        client.delete(f"/api/sessions/{sid}")
        r = client.get(f"/api/sessions/{sid}")
        assert r.status_code == 404

    def test_invalid_class_returns_422(self, client):
        body = _char_body()
        body["character"]["char_class"] = "bard"   # not supported
        r = client.post("/api/sessions", json=body)
        assert r.status_code == 422

    def test_invalid_race_returns_422(self, client):
        body = _char_body()
        body["character"]["race"] = "tiefling"   # not supported
        r = client.post("/api/sessions", json=body)
        assert r.status_code == 422


# ── Character sheet ────────────────────────────────────────────────────────────

class TestCharacterSheet:
    def test_get_character_returns_200(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        assert r.status_code == 200

    def test_character_name_matches(self, client):
        sid = client.post("/api/sessions", json=_char_body(name="Arya")).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        assert r.json()["name"] == "Arya"

    def test_fighter_hp_correct(self, client):
        # Fighter d10 + CON mod(14→+2) = 12
        sid = client.post("/api/sessions", json=_char_body(char_class="fighter")).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        assert r.json()["max_hp"] == 12

    def test_wizard_has_spells(self, client):
        body = _char_body(char_class="wizard", race="elf")
        body["character"]["ability_assignment"] = {
            "str": 8, "dex": 14, "con": 12, "int": 15, "wis": 13, "cha": 10
        }
        sid = client.post("/api/sessions", json=body).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        data = r.json()
        assert len(data["known_spells"]) > 0
        assert len(data["spell_slots"]) > 0

    def test_elf_has_dex_bonus(self, client):
        # Elf: +2 DEX, base assignment dex=14 → final dex=16
        body = _char_body(race="elf")
        body["character"]["ability_assignment"]["dex"] = 14
        sid = client.post("/api/sessions", json=body).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        assert r.json()["ability_scores"]["dex"] == 16

    def test_background_soldier_grants_skills(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        skills = r.json()["proficient_skills"]
        assert "athletics" in skills
        assert "intimidation" in skills

    def test_character_has_starting_equipment(self, client):
        sid = client.post("/api/sessions", json=_char_body(char_class="fighter")).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/character")
        equipped = r.json()["equipped"]
        assert "main_hand" in equipped
        assert "armor" in equipped

    def test_inventory_has_healing_potion(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/inventory")
        items = r.json()["inventory"]
        types = [i.get("type") for i in items]
        assert "healing_potion" in types

    def test_get_inventory_returns_gold(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/inventory")
        assert r.json()["gold"] > 0


# ── Game actions ───────────────────────────────────────────────────────────────

class TestGameActions:
    def test_narrative_action_returns_200(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I look around the tavern"})
        assert r.status_code == 200

    def test_action_returns_dm_response(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I examine the room carefully"})
        assert r.json()["dm_response"] == DM_CANNED

    def test_action_returns_intent_type(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I try to sneak past the guards"})
        assert r.json()["intent_type"] == "skill_check"

    def test_skill_check_has_mechanic_result(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I sneak past the goblin"})
        data = r.json()
        # Mechanic result should mention stealth or the check result
        assert len(data["mechanic_result"]) > 0

    def test_attack_starts_combat(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I attack the goblin"})
        data = r.json()
        assert data["in_combat"] is True
        assert data["combat"] is not None

    def test_combat_state_has_initiative_order(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "roll for initiative"})
        combat = r.json().get("combat")
        assert combat is not None
        assert "player" in combat["initiative_order"]

    def test_action_on_missing_session_returns_404(self, client, mock_dm):
        r = client.post("/api/sessions/no-such-id/action",
                        json={"action": "I look around"})
        assert r.status_code == 404

    def test_player_hp_in_response(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I sit down"})
        data = r.json()
        assert "player_hp" in data
        assert data["player_hp"] > 0

    def test_events_list_present(self, client, mock_dm):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/action",
                        json={"action": "I rest for a moment"})
        assert isinstance(r.json()["events"], list)


# ── Game state ─────────────────────────────────────────────────────────────────

class TestGameState:
    def test_get_state_returns_200(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/state")
        assert r.status_code == 200

    def test_state_has_player(self, client):
        sid = client.post("/api/sessions", json=_char_body(name="Kira")).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/state")
        assert r.json()["player"]["name"] == "Kira"

    def test_state_has_npcs(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/state")
        npcs = r.json()["npcs"]
        assert len(npcs) >= 2   # goblin_1, goblin_2

    def test_state_has_quests(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/state")
        assert len(r.json()["quests"]) >= 1

    def test_state_scene_is_string(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/state")
        assert isinstance(r.json()["scene"], str)

    def test_get_quests_returns_list(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/quests")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Reference data ─────────────────────────────────────────────────────────────

class TestReferenceData:
    def test_get_classes_has_fighter(self, client):
        r = client.get("/api/reference/classes")
        assert r.status_code == 200
        assert "fighter" in r.json()

    def test_get_classes_has_wizard(self, client):
        assert "wizard" in client.get("/api/reference/classes").json()

    def test_get_races_has_human(self, client):
        assert "human" in client.get("/api/reference/races").json()

    def test_get_npcs_has_goblin(self, client):
        assert "goblin" in client.get("/api/reference/npcs").json()

    def test_get_weapons_has_longsword(self, client):
        data = client.get("/api/reference/weapons").json()
        assert "longsword" in data

    def test_get_spells_has_firebolt(self, client):
        data = client.get("/api/reference/spells").json()
        assert "firebolt" in data

    def test_get_armor_returns_dict(self, client):
        r = client.get("/api/reference/armor")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


# ── Save / Load ────────────────────────────────────────────────────────────────

class TestSaveLoad:
    def test_save_game_returns_200(self, client, tmp_path):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/save", json={})
        assert r.status_code == 200
        assert r.json()["saved"] is True

    def test_save_creates_file(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/save", json={})
        path = r.json()["path"]
        assert os.path.exists(path)

    def test_load_nonexistent_slot_returns_404(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/load",
                        json={"slot": "no-such-slot-xyz"})
        assert r.status_code == 404

    def test_save_then_load_roundtrip(self, client):
        # Create, save, then reload
        sid = client.post("/api/sessions", json=_char_body(name="Roundtrip")).json()["session_id"]
        save_r = client.post(f"/api/sessions/{sid}/save", json={})
        assert save_r.json()["saved"] is True

        load_r = client.post(f"/api/sessions/{sid}/load", json={})
        assert load_r.json()["loaded"] is True

        char_r = client.get(f"/api/sessions/{sid}/character")
        assert char_r.json()["name"] == "Roundtrip"


# ── Character service unit tests ───────────────────────────────────────────────

class TestCharacterService:
    """Pure unit tests for character_service.build_player — no HTTP."""

    def _make_sm(self):
        from src.config_builder import SessionConfig
        from src.state_manager import StateManager
        config = SessionConfig(difficulty=3)
        sm = StateManager(config)
        sm.load_data_files()
        return sm

    def _ab(self, **kw):
        from backend.models import AbilityAssignment
        defaults = dict(str=10, dex=10, con=10, int=10, wis=10, cha=10)
        defaults.update(kw)
        return AbilityAssignment.model_validate(defaults)

    def _req(self, **kw):
        from backend.models import CharacterCreateRequest
        defaults = dict(
            name="X", race="human", char_class="fighter", background="soldier",
            ability_assignment=self._ab(),
        )
        defaults.update(kw)
        return CharacterCreateRequest(**defaults)

    def test_fighter_gets_chain_mail(self):
        from backend.character_service import build_player
        req = self._req(ability_assignment=self._ab(str=15, dex=12, con=14))
        player = build_player(req, self._make_sm())
        assert player.equipped.get("armor") == "chain_mail"

    def test_wizard_has_spell_slots(self):
        from backend.character_service import build_player
        req = self._req(race="elf", char_class="wizard", background="scholar",
                        ability_assignment=self._ab(str=8, dex=14, con=12, int=16, wis=13, cha=10))
        req.name = "Merlin"
        player = build_player(req, self._make_sm())
        assert len(player.spell_slots) > 0
        assert len(player.known_spells) > 0

    def test_racial_bonus_applied(self):
        from backend.character_service import build_player
        req = self._req(race="elf", char_class="rogue", background="criminal",
                        ability_assignment=self._ab(str=10, dex=14, con=12))
        player = build_player(req, self._make_sm())
        assert player.ability_scores.dex == 16   # 14 + 2 (elf bonus)

    def test_human_gets_all_plusone(self):
        from backend.character_service import build_player
        req = self._req(ability_assignment=self._ab(str=15, dex=12, con=14))
        player = build_player(req, self._make_sm())
        assert player.ability_scores.str == 16   # 15 + 1
        assert player.ability_scores.dex == 13   # 12 + 1
        assert player.ability_scores.con == 15   # 14 + 1

    def test_unknown_class_raises(self):
        from backend.character_service import build_player
        req = self._req(char_class="paladin")
        with pytest.raises(ValueError, match="Unknown class"):
            build_player(req, self._make_sm())

    def test_unknown_race_raises(self):
        from backend.character_service import build_player
        req = self._req(race="tiefling")
        with pytest.raises(ValueError, match="Unknown race"):
            build_player(req, self._make_sm())


# ── WebSocket streaming ────────────────────────────────────────────────────────

class TestWebSocket:
    def test_ws_invalid_session_sends_error(self, client):
        with client.websocket_connect("/ws/sessions/bad-id/dm") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "error"
            assert msg["code"] == "SESSION_NOT_FOUND"

    def test_ws_ping_returns_pong(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{sid}/dm") as ws:
            ws.send_text(json.dumps({"action": "ping"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "pong"

    def test_ws_meta_action_returns_done(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{sid}/dm") as ws:
            ws.send_text(json.dumps({"action": "check my stats"}))
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "done"

    def test_ws_narrative_sends_mechanic_result_then_done(self, client):
        sid = client.post("/api/sessions", json=_char_body()).json()["session_id"]

        # Mock the streaming generator to yield two tokens
        async def _fake_stream(dm, ctx, action):
            yield "The "
            yield "dungeon echoes."

        with patch("backend.ws.dm_stream.adm.generate_response_stream", _fake_stream):
            with client.websocket_connect(f"/ws/sessions/{sid}/dm") as ws:
                ws.send_text(json.dumps({"action": "I look around the room"}))

                frames = []
                for _ in range(10):   # collect up to 10 frames
                    try:
                        frames.append(json.loads(ws.receive_text()))
                        if frames[-1]["type"] == "done":
                            break
                    except Exception:
                        break

        types = [f["type"] for f in frames]
        assert "mechanic_result" in types
        assert "done" in types
