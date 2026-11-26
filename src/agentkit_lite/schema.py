"""A small, dependency-free validator for the JSON Schema subset agents need.

Supported keywords: type, required, properties, additionalProperties (bool),
enum, items, minItems, maxItems, minimum, maximum, minLength, maxLength.
Errors are returned as human-readable strings that are fed back to the model
on retry, so they are phrased as instructions.
"""

from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def _type_ok(value: Any, t: str) -> bool:
    if t in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[t])


_KNOWN = {"type", "required", "properties", "additionalProperties", "enum",
          "items", "minItems", "maxItems", "minimum", "maximum", "minLength",
          "maxLength", "description", "title"}


def check_schema(schema: Any, path: str = "$") -> list[str]:
    """Problems in the schema itself, reported when AGENT.md is loaded."""
    if not isinstance(schema, dict):
        return [f"{path}: schema must be a mapping"]
    problems = [f"{path}: unsupported keyword '{k}'" for k in schema if k not in _KNOWN]
    t = schema.get("type")
    if t is not None and not isinstance(t, (str, list)):
        problems.append(f"{path}: 'type' must be a string or a list")
    else:
        for x in (t if isinstance(t, list) else [t] if t is not None else []):
            if not isinstance(x, str) or x not in _TYPES:
                problems.append(f"{path}: unknown type '{x}'")
    for k in ("minItems", "maxItems", "minLength", "maxLength"):
        if k in schema and (not isinstance(schema[k], int) or isinstance(schema[k], bool)
                            or schema[k] < 0):
            problems.append(f"{path}: '{k}' must be a non-negative integer")
    for k in ("minimum", "maximum"):
        if k in schema and (not isinstance(schema[k], (int, float))
                            or isinstance(schema[k], bool)):
            problems.append(f"{path}: '{k}' must be a number")
    if "enum" in schema and not isinstance(schema["enum"], list):
        problems.append(f"{path}: 'enum' must be a list")
    if "required" in schema and not (isinstance(schema["required"], list)
                                     and all(isinstance(x, str) for x in schema["required"])):
        problems.append(f"{path}: 'required' must be a list of field names")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        problems.append(f"{path}: 'additionalProperties' must be true or false")
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        problems.append(f"{path}: 'properties' must be a mapping")
        props = {}
    for k, sub in (props or {}).items():
        problems += check_schema(sub, f"{path}.{k}")
    if "items" in schema:
        problems += check_schema(schema["items"], f"{path}[]")
    return problems


def _strict_eq(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_strict_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_strict_eq(a[k], b[k]) for k in a)
    return a == b


def _in_enum(value: Any, options: list) -> bool:
    # strict: True must not match 1, also inside lists and objects
    return any(_strict_eq(value, o) for o in options)


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, x) for x in types):
            return [f"{path}: expected {' or '.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and not _in_enum(value, schema["enum"]):
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field '{key}'")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errors += validate(value[key], sub, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                errors.append(f"{path}: unexpected fields {extra}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
    return errors
