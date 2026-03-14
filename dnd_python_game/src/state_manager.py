from typing import Dict, Any, List
from .config_builder import SessionConfig

class PlayerState:
    def __init__(self, char_class: str, hp: int, ac: int, location: str):
        self.char_class = char_class
        self.hp = hp
        self.max_hp = hp
        self.ac = ac
        self.location = location
        self.inventory: List[str] = []

class WorldState:
    def __init__(self, config: SessionConfig):
        self.config = config
        self.player = PlayerState(char_class="Fighter", hp=10, ac=15, location="Tavern")
        self.npcs: Dict[str, Any] = {
            "Goblins": {"quantity": 2, "hp": int(7 * config.modifiers.get("enemy_hp_multiplier", 1.0)), "ac": 12, "location": "Cave"}
        }
        self.active_quests: List[str] = ["Clear the goblin cave"]
        self.turn_history: List[str] = []

    def log_action(self, action: str, result: str):
        self.turn_history.append(f"Player Action: {action} | Result: {result}")

    def update_location(self, new_location: str):
        self.player.location = new_location

class StateManager:
    def __init__(self, config: SessionConfig):
        self.world = WorldState(config)
        
    def resolve_mechanic(self, action: str) -> str:
        # Placeholder for bridging with natural_20 mechanics or basic python dice rolls
        if "stealth" in action.lower():
            import random
            roll = random.randint(1, 20)
            if self.world.config.modifiers.get("player_advantage"):
                roll = max(roll, random.randint(1, 20))
            if self.world.config.modifiers.get("player_disadvantage"):
                roll = min(roll, random.randint(1, 20))
            return f"Stealth roll: {roll}. Success!" if roll >= 12 else f"Stealth roll: {roll}. Failure!"
        
        return "Action requires narrative resolution."

    def build_context_payload(self) -> Dict[str, Any]:
        return {
            "player": vars(self.world.player),
            "npcs": self.world.npcs,
            "quests": self.world.active_quests,
            "history": self.world.turn_history[-3:], # Last 3 turns
            "difficulty_rules": self.world.config.custom_rules if self.world.config.custom_rules else f"Difficulty Modifiers: {self.world.config.modifiers}"
        }
