"""
async_dm.py — Async wrappers around the blocking DMAgent.
Prevents Groq API calls from blocking the FastAPI event loop.
"""
import asyncio
import json
from typing import AsyncIterator

from src.dm_agent import DMAgent


async def generate_response(dm: DMAgent, context: dict, action: str) -> str:
    """
    Non-streaming: run DMAgent.generate_response in a thread pool.
    Returns the complete DM narrative string.
    """
    return await asyncio.to_thread(dm.generate_response, context, action, False)


async def generate_response_stream(
    dm: DMAgent, context: dict, action: str
) -> AsyncIterator[str]:
    """
    Streaming: yield DM tokens one at a time over a queue bridged from a
    background thread running the Groq streaming API.

    Usage::
        async for token in generate_response_stream(dm, ctx, action):
            await ws.send_text(token)
    """
    # Prepare the message exactly as DMAgent.generate_response does,
    # but keep history management here so the thread doesn't need it.
    compact = dm._compact_context(context)
    user_msg = (
        f"GAME STATE:\n{json.dumps(compact, indent=2)}"
        f"\n\nPLAYER ACTION: {action}"
    )
    dm.conversation_history.append({"role": "user", "content": user_msg})

    if len(dm.conversation_history) > dm._max_history:
        system_msg = dm.conversation_history[0]
        recent = dm.conversation_history[-(dm._max_history - 1):]
        dm.conversation_history = [system_msg] + recent

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _stream_in_thread():
        full_text = ""
        try:
            client = dm._get_client()
            stream = client.chat.completions.create(
                model=dm._model,
                messages=dm.conversation_history,
                max_tokens=600,
                temperature=0.85,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    loop.call_soon_threadsafe(queue.put_nowait, delta.content)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"[DM error: {exc}]")
        finally:
            # Persist full response to conversation history
            dm.conversation_history.append({"role": "assistant", "content": full_text})
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    asyncio.create_task(asyncio.to_thread(_stream_in_thread))

    while True:
        token = await queue.get()
        if token is None:
            break
        yield token
