from __future__ import annotations

IDEA_KEYS = ("Name", "Title", "Short Hypothesis", "Related Work", "Abstract", "Experiments", "Risk Factors and Limitations")

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "minItems": 1, "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "gap": {"type": "string"},
                       "question": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "integer"}}},
        "required": ["id", "gap", "question", "evidence"]}}},
    "required": ["questions"],
}

P1_SCHEMA = {"type": "object", "properties": {
    "hypothesis": {"type": "string"}, "derivation": {"type": "string"},
    "rivals": {"type": "array", "items": {"type": "string"}}},
    "required": ["hypothesis", "derivation", "rivals"]}

P2_SCHEMA = {"type": "object", "properties": {
    "operational_definitions": {"type": "array", "items": {"type": "string"}},
    "experiments": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "controls": {"type": "array", "items": {"type": "string"}},
    "decision_rule": {"type": "string"}, "feasibility": {"type": "string"}},
    "required": ["operational_definitions", "experiments", "controls", "decision_rule", "feasibility"]}

P3_SCHEMA = {"type": "object", "properties": {
    "nodes": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
        "test": {"type": "string"}, "positive": {"type": "string"}, "negative": {"type": "string"},
        "uninformative": {"type": "string"}}, "required": ["test", "positive", "negative", "uninformative"]}},
    "publishable_if_null": {"type": "boolean"}}, "required": ["nodes", "publishable_if_null"]}

P4_SCHEMA = {"type": "object", "properties": {
    "targets": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
        "reference": {"type": "integer"}, "claim": {"type": "string"}, "weakness": {"type": "string"},
        "test": {"type": "string"}, "if_miss": {"type": "string"}},
        "required": ["reference", "claim", "weakness", "test", "if_miss"]}}}, "required": ["targets"]}

IDEA_SCHEMA = {"type": "object", "properties": {key: {"type": "string"} for key in IDEA_KEYS},
               "required": list(IDEA_KEYS)}
DIRECT_IDEA_SCHEMA = {"type": "object", "properties": {"idea": {"type": "string"}}, "required": ["idea"]}
RANK_SCHEMA = {"type": "object", "properties": {
    "order": {"type": "array", "items": {"type": "integer"}}, "rationale": {"type": "string"}},
    "required": ["order", "rationale"]}


def require_fields(value: dict, keys: tuple[str, ...] | list[str], name: str) -> dict:
    missing = [key for key in keys if not isinstance(value.get(key), str) or not value[key].strip()]
    if missing:
        raise ValueError(f"{name} missing non-empty fields: {', '.join(missing)}")
    return value

