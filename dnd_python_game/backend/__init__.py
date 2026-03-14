"""
backend package — FastAPI REST + WebSocket server for the D&D 5e AI game.

Adds dnd_python_game/ to sys.path so 'from src.xxx import ...' resolves
regardless of the working directory the server is started from.
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Auto-load .env from dnd_python_game/ so GROQ_API_KEY is available without
# having to manually export it before starting uvicorn.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except ImportError:
    pass