"""Logging that cannot leak customer details by accident.

The pipeline only logs ids, labels and timings. This filter is a second net: it
masks email addresses, phone numbers and order/invoice numbers in anything that
still reaches a handler (for example an exception message from a library).
"""

import logging
import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b(?:NB-\d{4,6}|INV-\d{4}-\d{3,5})\b"), "[ref]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d"), "[phone]"),
]


def redact(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("triage")
    logger.setLevel(level)
    if not any(isinstance(f, RedactFilter) for f in logger.filters):
        logger.addFilter(RedactFilter())
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger
