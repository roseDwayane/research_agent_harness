"""Unit tests of the ideate_v2 core: schema validator, file primitives, errors, redaction, paths, retry."""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from ideate_v2 import errors, jsonio, paths, redact, retry, schema_lite
from ideate_v2.errors import ErrorRecord, IdeateError


# ------------------------------------------------------------------------------------------- schema_lite
@pytest.mark.parametrize("instance,schema,ok", [
    ({"a": 1}, {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}, True),
    ({}, {"type": "object", "required": ["a"]}, False),
    ({"a": True}, {"properties": {"a": {"type": "integer"}}}, False),            # bool is not an integer
    ("x-1", {"type": "string", "pattern": "^x-[0-9]$"}, True),
    ("y", {"enum": ["x"]}, False),
    ([1, 1], {"type": "array", "uniqueItems": True}, False),
    ({"b": 1}, {"type": "object", "additionalProperties": False, "properties": {"a": {}}}, False),
    (3, {"anyOf": [{"type": "string"}, {"type": "integer", "minimum": 2}]}, True),
    (3, {"oneOf": [{"type": "integer"}, {"type": "number"}]}, False),               # matches both
    ({"v": "a"}, {"$defs": {"s": {"type": "string"}}, "properties": {"v": {"$ref": "#/$defs/s"}}}, True),
    (None, {"type": ["string", "null"]}, True),
])
def test_schema_lite(instance, schema, ok):
    assert (schema_lite.validate(instance, schema) == []) is ok


def test_schema_lite_reports_paths():
    errs = schema_lite.validate({"a": [1, "x"]}, {"properties": {"a": {"items": {"type": "integer"}}}})
    assert errs == ["$.a[1]: expected integer, got str"]


# ------------------------------------------------------------------------------------------- jsonio
def test_atomic_write_is_lf_on_every_platform(tmp_path):
    p = tmp_path / "x.json"
    jsonio.write_json_atomic(p, {"a": ["b", "c"]})
    assert b"\r\n" not in p.read_bytes()
    assert not list(tmp_path.glob("*.tmp"))


def test_read_jsonl_reports_bad_lines_by_number(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1}\nnot json\n[1]\n{"b": 2}\n', encoding="utf-8")
    recs, problems = jsonio.read_jsonl(p)
    assert [r for r in recs] == [{"a": 1}, {"b": 2}]
    assert [x["line"] for x in problems] == [2, 3]


def test_torn_last_line_does_not_swallow_the_next_record(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a": 1}\n{"torn": ', encoding="utf-8")         # a crash mid-write
    jsonio.append_jsonl(p, {"b": 2})
    recs, problems = jsonio.read_jsonl(p)
    assert {"b": 2} in recs and len(problems) == 1


def test_concurrent_appends_lose_nothing(tmp_path):
    p = tmp_path / "events.jsonl"

    def writer(k):
        for i in range(40):
            jsonio.append_jsonl(p, {"w": k, "i": i})
    threads = [threading.Thread(target=writer, args=(k,)) for k in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    recs, problems = jsonio.read_jsonl(p)
    assert len(recs) == 200 and not problems


def test_stale_lock_is_broken(tmp_path):
    target = tmp_path / "f.jsonl"
    lock = tmp_path / "f.jsonl.lock"
    lock.write_text("999999")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    with jsonio.FileLock(target, timeout=1.0, stale_after=60):
        pass
    assert not lock.exists()


def test_held_lock_times_out(tmp_path):
    target = tmp_path / "f.jsonl"
    with jsonio.FileLock(target):
        with pytest.raises(jsonio.LockTimeout):
            with jsonio.FileLock(target, timeout=0.1):
                pass


def test_file_too_large(tmp_path):
    p = tmp_path / "big.json"
    p.write_text("[" + "1," * 100 + "1]", encoding="utf-8")
    with pytest.raises(jsonio.FileTooLarge):
        jsonio.read_json(p, max_bytes=10)


def test_hash_formats_match_the_legacy_ledger(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"abc")
    assert jsonio.sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert jsonio.sha256_json({"b": 1, "a": "é"}) == jsonio.sha256_json({"a": "é", "b": 1})


# ------------------------------------------------------------------------------------------- errors
def _rec(**kw):
    base = dict(error_code="IDEATE.TOOL.TIMEOUT", error_category="timeout", error_message="slow", severity="error",
                retryable=True, unit_id="A2.s", step_id="STEP-S2", run_id="r_20261022_100000_abcd",
                trace_id="0" * 32)
    base.update(kw)
    return ErrorRecord(**base)


def test_error_record_validates_its_fields():
    with pytest.raises(IdeateError):
        _rec(error_category="bogus")
    with pytest.raises(IdeateError):
        _rec(run_id="run-1")
    with pytest.raises(IdeateError):
        _rec(error_category="state")                               # code belongs to category timeout
    assert _rec().to_dict()["schema"] == "ideate-v2-error/1"


def test_error_record_redacts_message_and_context():
    r = _rec(error_message="GET https://x.org/?api_key=abc123", context={"token": "t0p", "n": 3})
    assert "abc123" not in r.error_message and r.context == {"token": "[REDACTED]", "n": 3}


def test_unit_check_codes_are_namespaced():
    assert errors.category_of("A2.c:R03") == "check_failed"
    assert errors.category_of("P5/K01-05:K02") == "check_failed"
    with pytest.raises(ValueError):
        errors.category_of("R03")


def test_from_exception_keeps_the_cause_chain():
    try:
        try:
            json.loads("{")
        except json.JSONDecodeError as inner:
            raise RuntimeError("could not load the index") from inner
    except RuntimeError as outer:
        wrapped = errors.from_exception(outer)
    assert wrapped.code == "IDEATE.INTERNAL" and wrapped.__cause__ is not None
    assert wrapped.context["cause_chain"][1].startswith("JSONDecodeError")
    assert errors.from_exception(jsonio.LockTimeout("x")).code == "IDEATE.STATE.LOCK_TIMEOUT"
    assert errors.from_exception(FileNotFoundError("x")).code == "IDEATE.ARTIFACT.MISSING"


def test_root_cause_is_cycle_safe():
    recs = {"E1": {"error_id": "E1", "parent_error_id": "E2"}, "E2": {"error_id": "E2", "parent_error_id": "E1"},
            "E3": {"error_id": "E3", "parent_error_id": "E1"}}
    root, chain = errors.root_cause(recs, "E3")
    assert chain[:3] == ["E3", "E1", "E2"] and root is not None


def test_every_code_has_a_known_category():
    assert all(cat in errors.CATEGORIES for cat, _ in errors.CODES.values())


# ------------------------------------------------------------------------------------------- redaction
def test_redaction_bounds_size_and_depth():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}
    assert "[depth limit]" in json.dumps(redact.redact(deep))
    assert redact.redact_text("x" * 5000).endswith("chars]")
    assert redact.redact({"items": list(range(500))})["items"][-1].startswith("[400 more")
    assert redact.redact_text("Authorization: Bearer abcdefghijkl") == "Authorization: [REDACTED]"


# ------------------------------------------------------------------------------------------- paths
def test_path_policy(tmp_path):
    root = tmp_path / "root"
    (root / "rd" / "_state").mkdir(parents=True)
    (root / "rd" / "step0_session_config.json").write_text("{}")
    (root / "plain").mkdir()
    pol = paths.PathPolicy((root.resolve(),))
    assert pol.resolve_run_dir("rd") == (root / "rd").resolve()
    for bad, code in (("../", "IDEATE.PATH.DENIED"), (str(tmp_path), "IDEATE.PATH.DENIED"),
                      ("plain", "IDEATE.PATH.NOT_A_RUN_DIR"), ("", "IDEATE.INPUT.INVALID"),
                      ("a\x00b", "IDEATE.INPUT.INVALID")):
        with pytest.raises(IdeateError) as e:
            pol.resolve_run_dir(bad)
        assert e.value.code == code, bad


def test_symlink_escape_is_denied(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    (outside / "_state").mkdir(parents=True)
    (outside / "step0_session_config.json").write_text("{}")
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted for this user on this platform")
    with pytest.raises(IdeateError) as e:
        paths.PathPolicy((root.resolve(),)).resolve_run_dir("link")
    assert e.value.code == "IDEATE.PATH.DENIED"


def test_env_roots(tmp_path):
    pol = paths.PathPolicy.from_env({"IDEATE_ALLOWED_ROOTS": f"{tmp_path}{os.pathsep}{tmp_path / 'b'}"})
    assert len(pol.roots) == 2


def test_observability_dir_and_components(tmp_path):
    assert paths.observability_dir(tmp_path, "r_20261022_100000_abcd").name == "r_20261022_100000_abcd"
    with pytest.raises(IdeateError):
        paths.observability_dir(tmp_path, "../x")
    assert paths.safe_component("A7.D@lee/../x") == "A7.D@lee_.._x"
    with pytest.raises(IdeateError):
        paths.safe_component("..")


# ------------------------------------------------------------------------------------------- retry
def test_backoff_is_capped_and_deterministic():
    b = {"base_s": 2.0, "factor": 2.0, "cap_s": 30.0, "jitter": "full"}
    assert retry.backoff_delay(b, 10, "s") == retry.backoff_delay(b, 10, "s") <= 30
    assert retry.backoff_delay({**b, "jitter": "none"}, 3, "s") == 8.0
    assert retry.backoff_delay(None, 3, "s") == 0.0


def test_retry_rejects_bad_arguments(reg):
    with pytest.raises(IdeateError):
        retry.decide(reg, "RP-NOPE", {"error_category": "timeout"}, 1, "orchestrator")
    with pytest.raises(IdeateError):
        retry.decide(reg, "RP-UNIT", {"error_category": "timeout"}, 0, "orchestrator")
    with pytest.raises(IdeateError):
        retry.decide(reg, "RP-UNIT", {"error_category": "nope"}, 1, "orchestrator")
