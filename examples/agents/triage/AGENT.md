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
    equipment_tag: {type: string, minLength: 3}
    discipline: {type: string, enum: [mechanical, electrical, instrumentation]}
    priority: {type: string, enum: [high, medium, low]}
    symptoms:
      type: array
      minItems: 1
      items: {type: string}
---
Classify this maintenance request.

- priority is "high" for safety risk, trips or stopped equipment, "low" when the
  requester defers it, otherwise "medium".

Request: {{request}}
