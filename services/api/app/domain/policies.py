from __future__ import annotations

import re


EMAIL_PATTERN = re.compile(r"(?P<name>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def redact_email(value: str) -> str:
    return EMAIL_PATTERN.sub("***@\\g<domain>", value)


def redact_name(value: str) -> str:
    parts = value.split()
    if not parts:
        return value
    if len(parts) == 1:
        return parts[0][0] + "***"
    return f"{parts[0][0]}*** {parts[-1][0]}***"


def classify_transfer_amount(amount: float) -> str:
    if amount >= 10_000:
        return "high"
    if amount >= 5_000:
        return "medium"
    return "low"
