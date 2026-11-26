"""Offline demo of retry-with-feedback and model fallback.

Run:  python examples/demo.py
The scripted backend simulates a small model that first breaks the contract
and then times out, and a larger model that answers correctly.
"""

import json
from pathlib import Path

from agentkit_lite import Agent, Registry, ScriptedBackend, TraceSink

HERE = Path(__file__).parent

backend = ScriptedBackend({
    "small-fast-model": [
        'Sure! {"equipment_tag": "P-203", "discipline": "mech", "priority": "urgent"}',
        TimeoutError("upstream timed out"),
    ],
    "larger-model": [
        '{"equipment_tag": "P-203", "discipline": "mechanical", '
        '"priority": "medium", "symptoms": ["leak"]}',
    ],
})

registry = Registry(HERE / "agents")
agent = Agent(registry.get("triage"), backend,
              trace=TraceSink(HERE / "traces.jsonl", redact=True))
result = agent.run(request="Pump P-203 seal is leaking, please schedule this week.")

print("ok:", result.ok, "| model:", result.model, "| attempts:", result.attempts)
print("output:", json.dumps(result.output))
for e in result.events:
    print(f"  {e['model']:<17} attempt {e['attempt']}  {e['status']:<15} "
          f"{'; '.join(e.get('errors', [])) or e.get('error', '')}")
