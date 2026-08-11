from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class PublishedMessage:
    message_id: str
    topic: str
    payload: dict[str, Any]


class LocalPubSubBus:
    """Local stand-in for Pub/Sub while preserving the integration boundary."""

    def __init__(self) -> None:
        self.messages: list[PublishedMessage] = []

    def publish(self, topic: str, payload: dict[str, Any]) -> PublishedMessage:
        message = PublishedMessage(
            message_id=f"local-pubsub-{uuid4().hex}",
            topic=topic,
            payload=payload,
        )
        self.messages.append(message)
        return message
