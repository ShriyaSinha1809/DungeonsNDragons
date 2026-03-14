from typing import Dict, Any

class SessionConfig:
    def __init__(self, difficulty: int, custom_rules: str = ""):
        self.difficulty = difficulty
        self.custom_rules = custom_rules
        self.modifiers = self._calculate_modifiers()

    def _calculate_modifiers(self) -> Dict[str, Any]:
        modifiers = {
            "enemy_hp_multiplier": 1.0,
            "player_advantage": False,
            "player_disadvantage": False
        }
        
        if self.difficulty == 1: # Storyteller
            modifiers["enemy_hp_multiplier"] = 0.5
            modifiers["player_advantage"] = True
        elif self.difficulty == 2: # Adventurer
            modifiers["enemy_hp_multiplier"] = 0.75
        elif self.difficulty == 3: # Heroic
            modifiers["enemy_hp_multiplier"] = 1.0
        elif self.difficulty == 4: # Tactician
            modifiers["enemy_hp_multiplier"] = 1.25
            modifiers["player_disadvantage"] = True
            
        return modifiers

def display_welcome_menu() -> SessionConfig:
    print("="*50)
    print("Welcome to Dynamic D&D 5e: The Multi-Agent Story")
    print("="*50)
    print("\nPlease select your difficulty:")
    print("1. Storyteller (Very Easy) - Enemies have -50% HP, you have advantage.")
    print("2. Adventurer (Easy) - Enemies have -25% HP.")
    print("3. Heroic (Normal) - Standard 5e Rules.")
    print("4. Tactician (Hard) - Enemies have +25% HP, you have disadvantage on saves.")
    print("5. Custom / Creative Mode - Define your own narrative rules.")
    
    while True:
        try:
            choice = int(input("\nEnter your choice (1-5): "))
            if 1 <= choice <= 4:
                return SessionConfig(difficulty=choice)
            elif choice == 5:
                custom_rules = input("\nEnter your custom narrative rules (e.g. 'All enemies are pacifists'): ")
                return SessionConfig(difficulty=5, custom_rules=custom_rules)
            else:
                print("Invalid choice. Please select 1-5.")
        except ValueError:
            print("Please enter a valid number.")

if __name__ == "__main__":
    config = display_welcome_menu()
    print("\nGame initialized with config:")
    print(f"Difficulty Level: {config.difficulty}")
    print(f"Modifiers: {config.modifiers}")
    if config.custom_rules:
        print(f"Custom Rules: {config.custom_rules}")
