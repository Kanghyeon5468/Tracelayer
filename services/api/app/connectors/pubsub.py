from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublishedMessage:
    topic: str
    payload: dict[str, Any]


class LocalPubSubBus:
    """Local stand-in for Pub/Sub while preserving the integration boundary."""

    def __init__(self) -> None:
        self.messages: list[PublishedMessage] = []

    def publish(self, topic: str, payload: dict[str, Any]) -> PublishedMessage:
        message = PublishedMessage(topic=topic, payload=payload)
        self.messages.append(message)
        return message
