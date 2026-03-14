from typing import Dict, Any

class IntentParser:
    """
    Parses raw text from the player to identify D&D 5e actionable intents.
    In a fully fleshed system, this could also be powered by a lightweight LLM.
    """
    def parse(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        
        # Skill Checks
        if any(word in text_lower for word in ['sneak', 'stealth', 'hide']):
            return {'type': 'skill_check', 'skill': 'stealth', 'intent': text}
        elif any(word in text_lower for word in ['look', 'search', 'investigate', 'perception']):
            return {'type': 'skill_check', 'skill': 'perception', 'intent': text}
            
        # Combat Actions
        elif any(word in text_lower for word in ['attack', 'hit', 'strike', 'shoot', 'stab']):
            return {'type': 'attack', 'intent': text}
            
        # Magic
        elif any(word in text_lower for word in ['cast', 'spell', 'magic']):
            return {'type': 'spell', 'intent': text}
            
        # Default fallback
        else:
            return {'type': 'narrative', 'intent': text}
