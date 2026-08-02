"""Run a local OpenAI-compatible dummy LLM API for manual testing."""

from __future__ import annotations

import argparse

import uvicorn

from corvus.llm.dummy_server import create_dummy_llm_app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corvus dummy OpenAI-compatible LLM API (returns a simulated success response)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--require-auth",
        action="store_true",
        help="Require Authorization: Bearer <token> on /v1/chat/completions",
    )
    args = parser.parse_args()

    app = create_dummy_llm_app(require_auth=args.require_auth)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
