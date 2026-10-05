"""JSON Schema validation.

Uses the ``jsonschema`` package when installed; otherwise falls back to a
small built-in validator that covers the subset of draft 2020-12 our schemas
use: type, enum, const, required, properties, additionalProperties, items,
minimum, maximum, minLength, pattern, minItems, $ref (local #/$defs/...),
anyOf.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool, "null": type(None),
}


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / f"{name}.schema.json", encoding="utf-8") as f:
        return json.load(f)


def _type_ok(value, t) -> bool:
    if isinstance(t, list):
        return any(_type_ok(value, x) for x in t)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def _validate(value, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"Only local refs supported: {ref}")
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        _validate(value, node, root, path, errors)
        return
    if "anyOf" in schema:
        if not any(not _collect(value, s, root, path) for s in schema["anyOf"]):
            errors.append(f"{path}: matches none of anyOf")
        return
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} doesn't match {schema['pattern']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required {req!r}")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                _validate(v, props[k], root, f"{path}.{k}", errors)
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unexpected property {k!r}")
                elif isinstance(extra, dict):
                    _validate(v, extra, root, f"{path}.{k}", errors)


def _collect(value, schema, root, path) -> list[str]:
    errs: list[str] = []
    _validate(value, schema, root, path, errs)
    return errs


def validate(instance, schema: dict) -> list[str]:
    """Return a list of error strings (empty when valid)."""
    try:
        import jsonschema  # type: ignore

        v = jsonschema.Draft202012Validator(schema)
        return [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}" for e in v.iter_errors(instance)]
    except ImportError:
        return _collect(instance, schema, schema, "$")


def validate_named(instance, name: str) -> list[str]:
    return validate(instance, load_schema(name))
