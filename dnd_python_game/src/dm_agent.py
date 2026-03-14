import json
from typing import Dict, Any
from .config_builder import SessionConfig

class DMAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.conversation_history = []
        
    def _build_persona(self, custom_rules: str, modifiers: Dict[str, Any]) -> str:
        base_prompt = (
            "You are an expert, dynamic Dungeon Master running a D&D 5e campaign. "
            "You will receive the current state of the game, recent turn history, and the player's action with any dice roll results. "
            "Your job is to vividly describe the outcome, narrate the world, advance the plot, and ask 'What do you do?' at the end."
        )
        if custom_rules:
            base_prompt += f"\nCRITICAL CUSTOM RULE: {custom_rules}. ALWAYS respect this rule."
        else:
            base_prompt += f"\nMECHANICAL MODIFIERS IN PLAY: {modifiers}."
            
        return base_prompt

    def start_session(self, config: 'SessionConfig') -> None:
        self.system_prompt = self._build_persona(config.custom_rules, config.modifiers)
        self.conversation_history.append({"role": "system", "content": self.system_prompt})

    def generate_response(self, context_payload: Dict[str, Any], player_action: str) -> str:
        # Context building for the LLM prompt
        state_context = f"CURRENT GAME STATE:\n{json.dumps(context_payload, indent=2)}\n\nPLAYER ACTION: {player_action}"
        
        self.conversation_history.append({"role": "user", "content": state_context})
        
        # NOTE: In a real implementation, this would make an API call to OpenAI, LangChain, Anthropic, etc.
        # Example: response = openai.ChatCompletion.create(model="gpt-4", messages=self.conversation_history)
        # response_text = response['choices'][0]['message']['content']
        
        # MOCK RESPONSE for structural testing:
        response_text = (
            f"[DM Agent (Mock)]: Given your state ({context_payload['player']['location']}) and your action '{player_action}', "
            f"you cautiously proceed. The air is damp. You spot movement ahead. What do you do?"
        )
        
        self.conversation_history.append({"role": "assistant", "content": response_text})
        return response_text
