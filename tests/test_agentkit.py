import json
import os
import time
from pathlib import Path

import pytest

from agentkit_lite import (Agent, AgentFailed, Registry, ScriptedBackend,
                           SpecError, TraceSink, extract_json, parse, validate)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/agents"
GOOD = ('{"equipment_tag": "P-1", "discipline": "mechanical", '
        '"priority": "low", "symptoms": ["leak"]}')


def spec_text(models="[m1, m2]", retries=1, extra=""):
    return f"""---
name: t
models: {models}
max_retries: {retries}
output_schema:
  type: object
  required: [priority]
  properties:
    priority: {{type: string, enum: [high, low]}}
{extra}---
Say {{{{thing}}}}
"""


def test_parse_and_render():
    s = parse(spec_text())
    assert s.models == ["m1", "m2"] and s.variables == ["thing"]
    assert s.render(thing="hi") == "Say hi"
    with pytest.raises(SpecError):
        s.render()


@pytest.mark.parametrize("bad", ["no front matter", "---\nname: x\n---\nbody",
                                 "---\nname: x\nmodels: []\n---\nb",
                                 "---\nname: x\nmodels: [a]\nmax_retries: 9\n---\nb"])
def test_invalid_specs(bad):
    with pytest.raises(SpecError):
        parse(bad)


def test_schema_validator():
    sch = {"type": "object", "required": ["a"], "additionalProperties": False,
           "properties": {"a": {"type": "integer", "minimum": 0},
                          "b": {"type": "array", "items": {"type": "string"}, "minItems": 1}}}
    assert validate({"a": 1, "b": ["x"]}, sch) == []
    errs = validate({"a": -1, "b": [], "c": 1}, sch)
    assert len(errs) == 3
    assert validate({"a": True}, sch)  # bool is not an integer
    assert validate("x", sch) == ["$: expected object, got str"]


def test_extract_json():
    assert extract_json('ok ```json\n{"a": [1]}\n```') == {"a": [1]}
    with pytest.raises(ValueError):
        extract_json("nothing")


def test_success_first_try():
    b = ScriptedBackend({"m1": ['{"priority": "high"}']})
    r = Agent(parse(spec_text()), b).run(thing="x")
    assert r.ok and r.model == "m1" and r.attempts == 1 and r.output == {"priority": "high"}


def test_retry_feeds_back_validation_errors():
    b = ScriptedBackend({"m1": ['{"priority": "urgent"}', '{"priority": "low"}']})
    r = Agent(parse(spec_text()), b).run(thing="x")
    assert r.ok and r.attempts == 2
    feedback = b.calls[1][1][-1]["content"]
    assert "rejected" in feedback and "urgent" in feedback


def test_fallback_after_retries_and_on_backend_error():
    b = ScriptedBackend({"m1": ["garbage", "still garbage"],
                         "m2": ['{"priority": "low"}']})
    r = Agent(parse(spec_text()), b).run(thing="x")
    assert r.ok and r.model == "m2" and r.attempts == 3
    b2 = ScriptedBackend({"m1": [TimeoutError("t")], "m2": ['{"priority": "low"}']})
    r2 = Agent(parse(spec_text()), b2).run(thing="x")
    assert r2.ok and r2.model == "m2"
    assert r2.events[0]["status"] == "backend_error"


def test_total_failure():
    b = ScriptedBackend({"m1": ["x", "y"], "m2": ["z", "w"]})
    r = Agent(parse(spec_text()), b).run(thing="x")
    assert not r.ok and r.attempts == 4
    with pytest.raises(AgentFailed):
        Agent(parse(spec_text()), ScriptedBackend({})).run(raise_on_fail=True, thing="x")


def test_trace_redaction(tmp_path):
    t = tmp_path / "t.jsonl"
    b = ScriptedBackend({"m1": ['{"priority": "confidential-value"}', '{"priority": "high"}']})
    Agent(parse(spec_text()), b, TraceSink(t, redact=True)).run(thing="secret plant data")
    raw = t.read_text()
    line = json.loads(raw.splitlines()[0])
    assert line["prompt"].startswith("sha256:")
    assert "secret" not in raw and "confidential-value" not in raw


def test_registry_hot_reload_and_bad_edit(tmp_path):
    d = tmp_path / "agents"
    (d / "t").mkdir(parents=True)
    f = d / "t" / "AGENT.md"
    f.write_text(spec_text())
    reg = Registry(d)
    assert reg.get("t").models == ["m1", "m2"]
    time.sleep(0.01)
    f.write_text(spec_text(models="[m3]"))
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert reg.get("t").models == ["m3"]
    f.write_text("broken")
    os.utime(f, (time.time() + 10, time.time() + 10))
    assert reg.get("t").models == ["m3"]  # last good version keeps serving
    assert reg.errors


def test_example_agent_end_to_end():
    reg = Registry(EXAMPLE)
    b = ScriptedBackend({"small-fast-model": ['{"priority": "urgent"}', TimeoutError()],
                         "larger-model": [GOOD]})
    r = Agent(reg.get("triage"), b).run(request="pump leaking")
    assert r.ok and r.model == "larger-model" and r.attempts == 3


def test_schema_problems_detected_at_load():
    bad = spec_text().replace("type: string, enum: [high, low]", "type: int")
    with pytest.raises(SpecError, match="unknown type 'int'"):
        parse(bad)


def test_enum_is_type_strict():
    assert validate(True, {"enum": [1]})
    assert validate(1, {"enum": [1]}) == []


def test_registry_forgets_deleted_and_renamed(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    a = d / "a.md"
    a.write_text(spec_text())
    reg = Registry(d)
    assert reg.names() == ["t"]
    a.write_text(spec_text().replace("name: t", "name: t2"))
    os.utime(a, (time.time() + 5, time.time() + 5))
    assert reg.names() == ["t2"]
    a.unlink()
    assert reg.names() == []


def test_redaction_covers_backend_errors_and_field_names(tmp_path):
    t = tmp_path / "t.jsonl"
    sch = spec_text().replace("properties:", "additionalProperties: false\n  properties:")
    b = ScriptedBackend({"m1": [ConnectionError("cannot reach host secret-host")],
                         "m2": ['{"priority": "low", "leaked_field_name": 1}',
                                '{"priority": "low"}']})
    Agent(parse(sch), b, TraceSink(t, redact=True)).run(thing="x")
    raw = t.read_text()
    assert "secret-host" not in raw and "leaked_field_name" not in raw


@pytest.mark.parametrize("old,new", [
    ("max_retries: 1", "max_retries: lots"),
    ("max_retries: 1", "max_retries: 1\ntemperature: hot"),
    ("type: string, enum: [high, low]", "type: {a: 1}"),
    ("  type: object", "  type: object\n  minItems: two"),
    ("  required: [priority]", "  required: priority"),
])
def test_bad_values_raise_spec_error(old, new):
    with pytest.raises(SpecError):
        parse(spec_text().replace(old, new, 1))


def test_bad_properties_type():
    bad = spec_text().replace("  properties:\n    priority: {type: string, enum: [high, low]}",
                              "  properties: [a]")
    with pytest.raises(SpecError):
        parse(bad)


def test_registry_survives_any_bad_edit(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    f = d / "a.md"
    f.write_text(spec_text())
    reg = Registry(d)
    f.write_text(spec_text().replace("max_retries: 1", "max_retries: lots"))
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert reg.get("t").max_retries == 1 and reg.errors


def test_enum_strict_inside_lists():
    assert validate([True], {"enum": [[1]]})
    assert validate([1], {"enum": [[1]]}) == []


@pytest.mark.parametrize("models", ["5", "{a: 1}", "[a, 2]", "[]"])
def test_bad_models_value(models):
    with pytest.raises(SpecError):
        parse(spec_text(models=models))


def test_non_utf8_file_is_spec_error(tmp_path):
    from agentkit_lite import load
    p = tmp_path / "bad.md"
    p.write_bytes(b"---\nname: \xff\n---\nx")
    with pytest.raises(SpecError):
        load(p)


def test_deep_schema_is_spec_error():
    deep = "{type: array, items: " * 1200 + "{type: string}" + "}" * 1200
    with pytest.raises(SpecError):
        parse(spec_text().replace("type: string, enum: [high, low]", f"type: array, items: {deep}"))


def test_infinite_retries_and_directories_are_handled(tmp_path):
    with pytest.raises(SpecError):
        parse(spec_text().replace("max_retries: 1", "max_retries: .inf"))
    d = tmp_path / "agents"
    d.mkdir()
    (d / "a.md").write_text(spec_text())
    (d / "x.md").mkdir()
    assert Registry(d).get("t").max_retries == 1


def test_yaml_aliases_and_null_name_rejected():
    bomb = "---\nname: t\nmodels: [m]\na: &a [x, x]\nb: [*a, *a]\n---\nhi\n"
    with pytest.raises(SpecError, match="aliases"):
        parse(bomb)
    with pytest.raises(SpecError, match="name"):
        parse("---\nname: null\nmodels: [m]\n---\nhi\n")


def test_trace_redaction_with_hmac_key(tmp_path):
    import hashlib
    import hmac
    t = tmp_path / "t.jsonl"
    b = ScriptedBackend({"m1": ['{"priority": "high"}']})
    Agent(parse(spec_text()), b, TraceSink(t, hmac_key=b"k3y")).run(thing="secret plant data")
    raw = t.read_text()
    line = json.loads(raw.splitlines()[0])
    assert line["reply"] == "hmac-sha256:" + hmac.new(
        b"k3y", b'{"priority": "high"}', hashlib.sha256).hexdigest()[:16]
    assert "secret" not in raw


def test_empty_hmac_key_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        TraceSink(tmp_path / "t.jsonl", hmac_key=b"")
