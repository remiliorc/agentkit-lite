"""agentkit-lite: production-minded LLM agents defined in editable AGENT.md files."""

from .agent import Agent, AgentFailed, RunResult, TraceSink, extract_json
from .backends import ScriptedBackend, openai_compatible
from .registry import Registry
from .schema import validate
from .spec import AgentSpec, SpecError, load, parse

__all__ = ["Agent", "AgentFailed", "RunResult", "TraceSink", "extract_json",
           "ScriptedBackend", "openai_compatible", "Registry", "validate",
           "AgentSpec", "SpecError", "load", "parse"]
__version__ = "0.1.0"
