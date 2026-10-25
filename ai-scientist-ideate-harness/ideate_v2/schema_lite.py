"""A small JSON Schema validator (the subset this module's schemas use), so validation needs no third-party package.

Supported keywords: type, enum, const, required, properties, additionalProperties, items, minItems, maxItems,
uniqueItems, minLength, maxLength, pattern, minimum, maximum, anyOf, oneOf, allOf, $ref (local "#/$defs/..." and
"#/definitions/..."). ``format`` and annotation keywords are ignored. Unknown keywords are ignored, as the spec says.
"""
from __future__ import annotations

import re
from typing import Any

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate(instance: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """Return a list of error messages ("<json path>: <problem>"); empty when the instance is valid."""
    root = schema if root is None else root
    errs: list[str] = []
    if "$ref" in schema:
        errs += validate(instance, _resolve(root, schema["$ref"]), root, path)
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](instance) for x in types):
            return errs + [f"{path}: expected {'/'.join(types)}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: expected {schema['const']!r}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{path}: {instance!r} does not match {schema['pattern']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = []
            for v in instance:
                if v in seen:
                    errs.append(f"{path}: duplicate item {v!r}")
                    break
                seen.append(v)
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(instance):
                errs += validate(v, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                errs.append(f"{path}: missing required property {k!r}")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errs.append(f"{path}: unexpected property {k!r}")
                elif isinstance(extra, dict):
                    errs += validate(v, extra, root, f"{path}.{k}")
    for sub in schema.get("allOf", []):
        errs += validate(instance, sub, root, path)
    if "anyOf" in schema and not any(not validate(instance, s, root, path) for s in schema["anyOf"]):
        errs.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema:
        n = sum(1 for s in schema["oneOf"] if not validate(instance, s, root, path))
        if n != 1:
            errs.append(f"{path}: matches {n} of oneOf (expected exactly 1)")
    return errs
