"""
app.py — FastAPI application factory for the D&D 5e backend.

Start with:
    cd dnd_python_game
    uvicorn backend.app:app --reload --port 8000
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse  # noqa: FileResponse used for SPA root
from fastapi.staticfiles import StaticFiles

from .session_store import SessionStore
from .routers import sessions, characters, game, reference
from .ws.dm_stream import router as ws_router

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create the shared session store. Shutdown: nothing to clean up."""
    app.state.store = SessionStore()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="D&D 5e AI Game Backend",
        description=(
            "REST + WebSocket backend powering a multi-agent D&D 5e storytelling game. "
            "The Dungeon Master is driven by the Groq LLM API."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router,   prefix="/api", tags=["Sessions"])
    app.include_router(characters.router, prefix="/api", tags=["Characters"])
    app.include_router(game.router,       prefix="/api", tags=["Game"])
    app.include_router(reference.router,  prefix="/api", tags=["Reference"])
    app.include_router(ws_router,                        tags=["WebSocket"])

    # Serve the game frontend
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/health", tags=["Meta"])
    def health():
        return {"status": "ok", "version": "1.0.0"}

    return app


# Module-level instance so uvicorn can import it directly
app = create_app()
