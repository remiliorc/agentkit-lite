"""Model backends: ``call(model, messages, temperature) -> str``."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, Protocol


class Backend(Protocol):
    def __call__(self, model: str, messages: list[dict], temperature: float) -> str: ...


class ScriptedBackend:
    """Deterministic backend for tests and demos.

    ``script`` maps a model name to a list of replies (strings) or exceptions,
    consumed in order. Every call is recorded in ``calls``.
    """

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, list[dict]]] = []

    def __call__(self, model: str, messages: list[dict], temperature: float) -> str:
        self.calls.append((model, [dict(m) for m in messages]))
        queue = self.script.get(model)
        if not queue:
            raise ConnectionError(f"model '{model}' unavailable")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def openai_compatible(base_url: str | None = None, api_key: str | None = None,
                      timeout: float = 120) -> Callable:
    """Any /v1/chat/completions endpoint (a hosted API or a local model server)."""
    base = (base_url or os.environ["AGENT_BASE_URL"]).rstrip("/")
    key = api_key if api_key is not None else os.environ.get("AGENT_API_KEY", "")

    def call(model: str, messages: list[dict], temperature: float) -> str:
        body = json.dumps({"model": model, "messages": messages,
                           "temperature": temperature}).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(f"{base}/chat/completions", data=body,
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    return call
