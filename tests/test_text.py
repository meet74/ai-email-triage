from triage.text import clean_body, detect_language


def test_quoted_history_is_split_off():
    new, quoted = clean_body("Thanks, works now.\n\nOn Tue, Nov 17, 2026 at 3:14 PM Support <s@example.com> wrote:\n> try rotating it")
    assert new == "Thanks, works now." and "try rotating" in quoted


def test_gt_quoting_and_outlook_headers():
    assert clean_body("Hi\n> old stuff")[0] == "Hi"
    new, quoted = clean_body("Hi\n\nFrom: A <a@example.com>\nSent: Monday\nTo: b\n\nold")
    assert new == "Hi" and "Sent: Monday" in quoted


def test_signature_and_mobile_footer_removed_but_name_kept():
    assert clean_body("Please call.\n\nThanks,\nDana\n\nSent from my iPhone")[0].endswith("Dana")
    assert "555" not in clean_body("Hi\n\nDana\n-- \nDana Ortiz | 555-0100")[0]


def test_forwarded_content_is_kept():
    body = "Please handle.\n\n---------- Forwarded message ---------\nFrom: A\nOne section bent."
    assert "One section bent" in clean_body(body)[0]


def test_language_detection():
    assert detect_language("Bonjour, ma commande n'est pas arrivée et je voudrais un suivi merci") == "fr"
    assert detect_language("Hola, mi pedido no ha llegado y quisiera saber con usted el estado") == "es"
    assert detect_language("Hello, where is my order? Thanks for your help") == "en"
    assert detect_language("") == "en"
