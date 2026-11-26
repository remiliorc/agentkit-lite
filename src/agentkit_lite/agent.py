"""Agent execution: render -> call -> parse -> validate -> retry -> fall back."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backends import Backend
from .schema import validate
from .spec import AgentSpec

_DECODER = json.JSONDecoder()


def extract_json(text: str) -> Any:
    """First JSON object or array in a reply (tolerates fences and chatter)."""
    for i, ch in enumerate(text or ""):
        if ch in "{[":
            try:
                return _DECODER.raw_decode(text, i)[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found in the reply")


class AgentFailed(RuntimeError):
    def __init__(self, message: str, result: "RunResult"):
        super().__init__(message)
        self.result = result


@dataclass
class RunResult:
    run_id: str
    agent: str
    ok: bool
    output: Any = None
    model: str | None = None
    attempts: int = 0
    events: list[dict] = field(default_factory=list)


class TraceSink:
    """Append-only JSONL trace. With ``redact`` the prompt and reply text are
    replaced by a short digest. A plain SHA-256 can be reversed by guessing
    for short or predictable texts; pass ``hmac_key`` (kept outside the trace)
    to use a keyed HMAC-SHA256 instead."""

    def __init__(self, path: str | Path | None = None, redact: bool = True,
                 hmac_key: bytes | None = None):
        self.path = Path(path) if path else None
        if hmac_key is not None and not hmac_key:
            raise ValueError("hmac_key must not be empty")
        self.redact = redact
        self.hmac_key = hmac_key

    def _digest(self, text: str) -> str:
        if self.hmac_key:
            mac = hmac.new(self.hmac_key, text.encode(), hashlib.sha256)
            return "hmac-sha256:" + mac.hexdigest()[:16]
        return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    def write(self, event: dict) -> None:
        if not self.path:
            return
        e = dict(event)
        if self.redact:
            for k in ("prompt", "reply"):
                if isinstance(e.get(k), str):
                    e[k] = self._digest(e[k])
            if "errors" in e:  # validation messages may echo reply values
                e["errors"] = [re.sub(r"(, got .*|unexpected fields .*)$",
                                      lambda m: "" if m.group(0).startswith(",")
                                      else "unexpected fields", x)
                               for x in e["errors"]]
            if isinstance(e.get("error"), str):  # backend error text may echo input
                e["error"] = e["error"].split(":", 1)[0]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


class Agent:
    def __init__(self, spec: AgentSpec, backend: Backend,
                 trace: TraceSink | None = None):
        self.spec = spec
        self.backend = backend
        self.trace = trace or TraceSink()

    def run(self, raise_on_fail: bool = False, **inputs: str) -> RunResult:
        spec = self.spec
        prompt = spec.render(**inputs)
        res = RunResult(run_id=uuid.uuid4().hex[:12], agent=spec.name, ok=False)

        for model in spec.models:
            messages = ([{"role": "system", "content": spec.system}] if spec.system else [])
            messages.append({"role": "user", "content": prompt})
            for attempt in range(spec.max_retries + 1):
                res.attempts += 1
                t0 = time.perf_counter()
                event = {"run_id": res.run_id, "agent": spec.name, "model": model,
                         "attempt": attempt, "prompt": messages[-1]["content"]}
                try:
                    reply = self.backend(model, messages, spec.temperature)
                except Exception as e:  # transport error -> next model
                    event.update(status="backend_error", error=f"{type(e).__name__}: {e}",
                                 latency_s=round(time.perf_counter() - t0, 4))
                    self._log(res, event)
                    break
                event.update(reply=reply, latency_s=round(time.perf_counter() - t0, 4))
                errors = self._check(reply)
                if not errors:
                    event["status"] = "ok"
                    self._log(res, event)
                    res.ok, res.model = True, model
                    res.output = extract_json(reply) if spec.output_schema else reply
                    return res
                event.update(status="invalid_output", errors=errors)
                self._log(res, event)
                messages = messages + [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": (
                        "Your previous answer was rejected:\n- " + "\n- ".join(errors)
                        + "\nReturn ONLY corrected JSON.")},
                ]
        if raise_on_fail:
            raise AgentFailed(f"agent '{spec.name}' failed on all models", res)
        return res

    def _check(self, reply: str) -> list[str]:
        if not self.spec.output_schema:
            return [] if reply.strip() else ["empty reply"]
        try:
            value = extract_json(reply)
        except ValueError as e:
            return [str(e)]
        return validate(value, self.spec.output_schema)

    def _log(self, res: RunResult, event: dict) -> None:
        res.events.append({k: v for k, v in event.items() if k not in ("prompt",)})
        self.trace.write(event)
