import json
import logging
import pathlib

from conftest import email, good_output
from triage.logging_setup import redact, setup_logging

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "emails.jsonl"


def test_pipeline_logs_contain_no_customer_text(make_engine, caplog):
    setup_logging("INFO")
    engine, _ = make_engine("garbage", good_output())
    with caplog.at_level(logging.INFO, logger="triage"):
        engine.triage(email(**{"from": "Dana Ortiz <dana.ortiz@example.com>", "subject": "Secret subject line",
                               "body": "My card ends 4242, call 416-555-0199. Order NB-10482.\n\nDana Ortiz"}))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "triaged id=" in text
    for leak in ("dana.ortiz", "Dana", "Secret subject", "4242", "555-0199", "NB-10482"):
        assert leak not in text


def test_redact_masks_identifiers():
    out = redact("mail dana@example.com about NB-10482 or INV-2026-0123, phone +1 416 555 0199")
    assert "dana@" not in out and "NB-10482" not in out and "INV-2026" not in out and "555 0199" not in out


def test_dataset_is_well_formed_and_fictional():
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 80 and len({r["id"] for r in rows}) == 80
    cats = {r["expected"]["category"] for r in rows}
    assert cats == {"support", "sales_lead", "billing", "complaint", "spam", "other"}
    assert sum(1 for r in rows if "injection" in r) == 3
    assert {r["expected"]["language"] for r in rows} >= {"en", "fr", "es"}
    for r in rows:
        assert "example." in r["from"], r["id"]
