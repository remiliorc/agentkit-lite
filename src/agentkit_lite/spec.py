"""AGENT.md: an agent defined as a Markdown file with YAML front matter.

Domain experts can edit the prompt, the model order or the output contract
without touching code. Example:

    ---
    name: triage
    models: [small-fast-model, larger-model]
    temperature: 0
    max_retries: 2
    output_schema:
      type: object
      required: [priority]
      properties:
        priority: {type: string, enum: [high, medium, low]}
    ---
    Classify this request: {{request}}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .schema import check_schema

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class SpecError(ValueError):
    pass


@dataclass
class AgentSpec:
    name: str
    models: list[str]
    prompt: str
    temperature: float = 0.0
    max_retries: int = 2
    output_schema: dict | None = None
    system: str = ""
    path: Path | None = None
    mtime: float = 0.0
    variables: list[str] = field(default_factory=list)

    def render(self, **inputs: str) -> str:
        missing = [v for v in self.variables if v not in inputs]
        if missing:
            raise SpecError(f"agent '{self.name}' missing inputs: {missing}")
        return _VAR.sub(lambda m: str(inputs[m.group(1)]), self.prompt)


def parse(text: str, path: Path | None = None) -> AgentSpec:
    m = _FRONT.match(text)
    if not m:
        raise SpecError("AGENT.md must start with a '---' YAML front matter block")
    try:
        # anchors/aliases are never needed in an agent definition and can be
        # used to build exponentially large documents ("billion laughs")
        if any(isinstance(ev, yaml.AliasEvent) for ev in yaml.parse(m.group(1))):
            raise SpecError("YAML aliases are not allowed in AGENT.md")
        meta = yaml.safe_load(m.group(1)) or {}
    except RecursionError:
        raise SpecError("front matter is nested too deeply")
    except yaml.YAMLError as e:
        raise SpecError(f"invalid front matter: {e}") from e
    if not isinstance(meta, dict):
        raise SpecError("front matter must be a mapping")
    for key in ("name", "models"):
        if key not in meta:
            raise SpecError(f"front matter needs '{key}'")
    if not isinstance(meta["name"], str) or not meta["name"].strip():
        raise SpecError("'name' must be a non-empty string")
    models = meta["models"]
    if isinstance(models, str):
        models = [models]
    if not isinstance(models, list) or not models or not all(isinstance(x, str) for x in models):
        raise SpecError("'models' must be a non-empty list of model names")
    try:
        retries = int(meta.get("max_retries", 2))
        temperature = float(meta.get("temperature", 0.0))
    except (TypeError, ValueError, OverflowError):
        raise SpecError("'max_retries' must be an integer and 'temperature' a number")
    if not 0 <= retries <= 5:
        raise SpecError("'max_retries' must be between 0 and 5")
    if not 0 <= temperature <= 2:
        raise SpecError("'temperature' must be between 0 and 2")
    schema = meta.get("output_schema")
    if schema is not None:
        try:
            problems = check_schema(schema)
        except RecursionError:
            raise SpecError("output_schema is nested too deeply")
        if problems:
            raise SpecError("invalid output_schema: " + "; ".join(problems))
    body = m.group(2).strip()
    return AgentSpec(
        name=str(meta["name"]), models=models, prompt=body,
        temperature=temperature,
        max_retries=retries, output_schema=meta.get("output_schema"),
        system=str(meta.get("system", "")), path=path,
        mtime=path.stat().st_mtime if path else 0.0,
        variables=sorted(set(_VAR.findall(body))),
    )


def load(path: str | Path) -> AgentSpec:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise SpecError(f"{p.name} is not valid UTF-8")
    except OSError as e:
        raise SpecError(f"cannot read {p.name}: {type(e).__name__}")
    return parse(text, p)
