from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from app.config import Settings


@dataclass(frozen=True)
class PublishedMessage:
    message_id: str
    topic: str
    payload: dict[str, Any]


class PubSubBus(Protocol):
    def publish(self, topic: str, payload: dict[str, Any]) -> PublishedMessage:
        ...


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


class GooglePubSubBus:
    """Publishes investigation work to Google Cloud Pub/Sub."""

    def __init__(self, settings: Settings) -> None:
        if not settings.google_cloud_project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Google Pub/Sub.")
        self.settings = settings
        self.publisher = self._build_publisher()

    def publish(self, topic: str, payload: dict[str, Any]) -> PublishedMessage:
        topic_path = self._topic_path(topic)
        # Publishing hands off interactive requests to the Cloud Run worker path.
        message_id = self.publisher.publish(
            topic_path,
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            source="tracelayer-api",
        ).result(timeout=10)
        return PublishedMessage(message_id=message_id, topic=topic_path, payload=payload)

    def _topic_path(self, topic: str) -> str:
        if topic.startswith("projects/"):
            return topic
        return self.publisher.topic_path(self.settings.google_cloud_project, topic)

    @staticmethod
    def _build_publisher():
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-pubsub is required for PUBSUB_BACKEND=google. "
                "Install the cloud extra."
            ) from exc

        return pubsub_v1.PublisherClient()


def create_pubsub_bus(settings: Settings) -> PubSubBus:
    backend = settings.resolved_pubsub_backend
    if backend == "local":
        return LocalPubSubBus()
    if backend == "google":
        return GooglePubSubBus(settings)
    raise ValueError(f"Unsupported PUBSUB_BACKEND: {settings.pubsub_backend}")
