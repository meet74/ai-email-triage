import pytest

from conftest import email
from triage.prefilter import prefilter


@pytest.mark.parametrize("sender,subject,body,kind", [
    ("mailer-daemon@example.com", "Undeliverable: hi", "Your message could not be delivered.", "auto_reply"),
    ("a@example.com", "Automatic reply: order", "I am out of the office.", "auto_reply"),
    ("a@example.com", "Réponse automatique : commande", "Je suis absent.", "auto_reply"),
    ("newsletter@shop.example.com", "Weekly", "Big news.\nUnsubscribe at any time.", "newsletter"),
    ("a@example.com", "Hi", "View this email in your browser\nSale!\nUnsubscribe", "newsletter"),
    ("x@example.net", "Alert", "Your account has been suspended. Verify your account: http://example.net/login", "phishing"),
    ("a@example.com", "SEO", "Guaranteed first page ranking for your site", "spam"),
])
def test_obvious_cases_are_caught(sender, subject, body, kind):
    hit = prefilter(sender, subject, body)
    assert hit and hit.kind == kind


@pytest.mark.parametrize("sender,subject,body", [
    ("a@example.com", "Please unsubscribe me", "Please unsubscribe me from your emails. Thanks, Julie"),
    ("a@example.com", "Order NB-10482", "Where is my order? I have not received it."),
    ("a@example.com", "Account question", "Is my account suspended? I cannot log in to the shop."),
    ("a@example.com", "Wholesale", "We want to rank your tents first in our shop catalogue."),
    ("a@example.com", "Thanks", "Out of office next week, so please ship after Monday. Can you do that?"),
])
def test_real_customers_are_not_caught(sender, subject, body):
    assert prefilter(sender, subject, body) is None


def test_hit_skips_the_model(make_engine):
    engine, client = make_engine()
    res = engine.triage(email(**{"from": "newsletter@deals.example.com", "subject": "Sale", "body": "Buy now\nUnsubscribe"}))
    assert client.calls == []
    assert res.category == "spam" and res.meta.source == "rules" and res.meta.skip_reason == "newsletter"
    assert res.draft_reply == ""
