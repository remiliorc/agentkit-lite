# agentkit-lite

LLM agents whose behaviour lives in an **editable `AGENT.md` file**. The domain
expert owns the prompt, the model order and the output contract; the code
enforces that contract.

The library is built for the unglamorous failure modes of production:

- **Contract validation**: replies are parsed and checked against a JSON Schema
  subset defined in the front matter.
- **Retry with feedback**: a rejected reply goes back to the model together with
  the exact validation errors, so it can correct itself.
- **Model fallback**: if a model keeps breaking the contract or the call fails
  (timeout, connection error), the next model in the list takes over.
- **Hot reload with a safety net**: edit `AGENT.md` and the next call uses it. A
  broken edit (including an invalid output schema, checked at load time) is
  reported, and the last valid version keeps serving. Deleted or renamed agents
  are dropped.
- **Redacted traces**: one JSONL event per attempt (model, status, latency,
  errors). By default, prompt and reply text are stored only as hashes, and
  values the model wrote, unexpected field names and backend error details are
  removed.

The only dependency is PyYAML. Backends are plain callables: a scripted backend
for tests, and any OpenAI-compatible endpoint (a hosted API or a local model
server).

## An agent

```markdown
---
name: triage
models: [small-fast-model, larger-model]
temperature: 0
max_retries: 2
system: You are a maintenance planner. Answer with JSON only.
output_schema:
  type: object
  additionalProperties: false
  required: [equipment_tag, discipline, priority, symptoms]
  properties:
    discipline: {type: string, enum: [mechanical, electrical, instrumentation]}
    priority:   {type: string, enum: [high, medium, low]}
    ...
---
Classify this maintenance request.
Request: {{request}}
```

```python
from agentkit_lite import Agent, Registry, TraceSink, openai_compatible

registry = Registry("agents/")
agent = Agent(registry.get("triage"),
              openai_compatible("http://localhost:8080/v1"),
              trace=TraceSink("traces.jsonl"))
result = agent.run(request="Pump P-203 seal is leaking, schedule this week.")
result.ok, result.model, result.output
```

`openai_compatible()` without arguments reads `AGENT_BASE_URL` and, optionally,
`AGENT_API_KEY` from the environment. Keys never go in code or in `AGENT.md`.

## Offline demo

```bash
pip install -e ".[dev]"
pytest -q
PYTHONPATH=src python examples/demo.py
```

```
ok: True | model: larger-model | attempts: 3
output: {"equipment_tag": "P-203", "discipline": "mechanical", "priority": "medium", "symptoms": ["leak"]}
  small-fast-model  attempt 0  invalid_output  $: missing required field 'symptoms'; $.discipline: must be one of [...], got 'mech'; ...
  small-fast-model  attempt 1  backend_error   TimeoutError: upstream timed out
  larger-model      attempt 0  ok
```

The small model first breaks the contract and gets its errors back. It then times
out, and the larger model answers correctly.

## Design choices

- **Why a schema subset and not `jsonschema`?** The subset (type, required,
  properties, additionalProperties, enum, items, min/max) covers agent contracts.
  Its error messages are written as instructions for the model.
- **Why stop retrying a model after a backend error?** A timeout usually means
  the model or its host is overloaded. Moving on to the next model gets an answer
  sooner than hammering the same one.
- **Why hash by default?** Traces are often shipped to shared tooling. Hashes
  still let you correlate identical prompts without storing their text. A plain
  hash is not encryption: short or predictable texts can be recovered by
  guessing. Pass `TraceSink(path, hmac_key=...)` with a key kept outside the
  traces to use a keyed HMAC instead, and treat traces as internal data either way.

## License

MIT
