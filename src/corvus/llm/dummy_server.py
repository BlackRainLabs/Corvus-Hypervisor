"""OpenAI-compatible dummy LLM API for local testing."""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

DEFAULT_SUCCESS_MESSAGE = "Success: simulated LLM response for testing."


def build_chat_completion_response(
    *,
    model: str,
    content: str = DEFAULT_SUCCESS_MESSAGE,
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-corvus-dummy",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def create_dummy_llm_app(*, require_auth: bool = False) -> FastAPI:
    app = FastAPI(title="Corvus Dummy LLM API", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        if require_auth:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="missing bearer token")

        body = await request.json()
        model = str(body.get("model", "dummy-v1"))
        messages = body.get("messages") or []
        last_user = ""
        for message in reversed(messages):
            if str(message.get("role")) == "user":
                last_user = str(message.get("content", ""))
                break
        content = DEFAULT_SUCCESS_MESSAGE
        if last_user:
            content = f"{DEFAULT_SUCCESS_MESSAGE} (echo: {last_user})"
        prompt_tokens = max(
            sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict)),
            1,
        )
        completion_tokens = len(content)

        tools = body.get("tools") or []

        if body.get("stream"):
            async def event_stream():
                if tools:
                    fn = (tools[0].get("function") or {})
                    tool_name = str(fn.get("name", "echo"))
                    open_frag = {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_dummy_1",
                                            "type": "function",
                                            "function": {"name": tool_name, "arguments": ""},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ]
                    }
                    yield f"data: {json.dumps(open_frag)}\n\n"
                    for piece in ('{"text": ', '"hi"}'):
                        arg_frag = {
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [
                                            {"index": 0, "function": {"arguments": piece}}
                                        ]
                                    },
                                    "finish_reason": None,
                                }
                            ]
                        }
                        yield f"data: {json.dumps(arg_frag)}\n\n"
                    tool_final = {
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": 1,
                            "total_tokens": prompt_tokens + 1,
                        },
                    }
                    yield f"data: {json.dumps(tool_final)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                chunk_size = 12
                for offset in range(0, len(content), chunk_size):
                    piece = content[offset : offset + chunk_size]
                    payload = {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": piece},
                                "finish_reason": None,
                            }
                        ]
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                final_payload = {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                }
                yield f"data: {json.dumps(final_payload)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        return JSONResponse(
            build_chat_completion_response(
                model=model,
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    return app


def pick_ephemeral_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class DummyLlmServer:
    """Background OpenAI-compatible HTTP server for pytest and manual testing."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        require_auth: bool = False,
    ) -> None:
        self.host = host
        self.port = port or pick_ephemeral_port(host)
        self.require_auth = require_auth
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    @property
    def health_url(self) -> str:
        return f"http://{self.host}:{self.port}/health"

    async def start(self) -> None:
        app = create_dummy_llm_app(require_auth=self.require_auth)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        await self._wait_until_ready()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
                with asyncio.suppress(asyncio.CancelledError):
                    await self._task
        self._server = None
        self._task = None

    async def _wait_until_ready(self) -> None:
        deadline = asyncio.get_running_loop().time() + 5.0
        async with httpx.AsyncClient() as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(self.health_url, timeout=0.5)
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
        raise RuntimeError(f"dummy LLM server failed to start on {self.base_url}")

    async def __aenter__(self) -> DummyLlmServer:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()
