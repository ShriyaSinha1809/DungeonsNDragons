import sys
from config_builder import display_welcome_menu
from state_manager import StateManager
from dm_agent import DMAgent

def main():
    # Phase 1: Initialization
    config = display_welcome_menu()
    
    print("\n--- Initializing Session ---")
    
    # Phase 2: Architecture Setup
    statbe_manager = StateManager(config)
    dm = DMAgent(system_prompt="")
    dm.start_session(config)
    
    input("Press Enter to begin your adventure...")
    print("\n" + "="*50)
    print("Welcome to your new world!")
    print("You find yourself in a dimly lit Tavern. A group of Goblins is rumored to be hiding in a nearby Cave.")
    print("What do you do?")
    print("="*50 + "\n")
    
    # Phase 3: The Game Loop
    while True:
        try:
            # Step 1: Input Collection
            player_action = input("\n> ")
            
            if player_action.lower() in ['quit', 'exit']:
                print("Farewell, adventurer!")
                break
                
            print("\n[Evaluating Action...]")
            
            # Step 2 & 3: Intent Parsing & Mechanic Resolution
            mechanic_result = state_manager.resolve_mechanic(player_action)
            action_log = f"Player attempted: '{player_action}'. System Result: {mechanic_result}"
            state_manager.world.log_action(player_action, mechanic_result)
            
            if "stealth" in player_action.lower() and "Success" in mechanic_result:
                state_manager.world.update_location("Sewer/Shadows")
                
            # Step 4: Context Payload construction
            context_payload = state_manager.build_context_payload()
            
            # Step 5: Narrative Generation via DM Agent
            print("\n[DM is thinking...]")
            dm_response = dm.generate_response(context_payload, action_log)
            
            # Step 6: Output & Loop Reset
            print("\n" + "~"*50)
            print(dm_response)
            print("~"*50)
            
        except KeyboardInterrupt:
            print("\nSession interrupted. Farewell!")
            sys.exit(0)

if __name__ == "__main__":
    main()
