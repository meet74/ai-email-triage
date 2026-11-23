import json

import pytest

from conftest import ScriptedClient, email, good_output
from triage.schema import SchemaError, parse_model_output


def test_valid_output_parses():
    r = parse_model_output(good_output())
    assert r.category == "support" and r.extracted.order_id == "NB-10482"


def test_code_fence_and_leading_text_are_tolerated():
    assert parse_model_output("```json\n" + good_output() + "\n```").priority == "normal"
    assert parse_model_output("Here you go:\n" + good_output()).priority == "normal"


@pytest.mark.parametrize("patch", [
    {"category": "refund"},
    {"priority": "high"},
    {"confidence": 1.4},
    {"reasons": []},
    {"unexpected": 1},
])
def test_invalid_values_are_rejected(patch):
    data = json.loads(good_output())
    data.update(patch)
    with pytest.raises(SchemaError):
        parse_model_output(json.dumps(data))


def test_missing_key_and_bad_action_rejected():
    data = json.loads(good_output())
    del data["summary"]
    with pytest.raises(SchemaError):
        parse_model_output(json.dumps(data))
    data = json.loads(good_output())
    data["extracted"]["requested_action"] = "give_everything"
    with pytest.raises(SchemaError):
        parse_model_output(json.dumps(data))


def test_not_json_rejected():
    with pytest.raises(SchemaError):
        parse_model_output("I cannot do that")


def test_blank_strings_become_none():
    data = json.loads(good_output())
    data["extracted"]["company"] = "  "
    data["extracted"]["product"] = "null"
    r = parse_model_output(json.dumps(data))
    assert r.extracted.company is None and r.extracted.product is None


def test_error_text_does_not_echo_input_values():
    data = json.loads(good_output())
    data["category"] = "secret-customer-text@example.com"
    with pytest.raises(SchemaError) as exc:
        parse_model_output(json.dumps(data))
    assert "secret-customer-text" not in str(exc.value)


def test_one_repair_retry_then_success(make_engine):
    engine, client = make_engine("not json at all", good_output())
    res = engine.triage(email())
    assert res.meta.repaired and res.meta.source == "llm" and not res.meta.degraded
    assert len(client.calls) == 2
    second = client.calls[1][1]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert "could not be used" in second[-1]["content"]


def test_two_bad_outputs_fall_back_to_human(make_engine):
    engine, client = make_engine("nope", '{"category": "support"}')
    res = engine.triage(email())
    assert len(client.calls) == 2  # exactly one retry
    assert res.meta.source == "fallback" and res.meta.degraded
    assert res.draft_reply == "" and res.meta.skip_reason is None  # still goes to a person
