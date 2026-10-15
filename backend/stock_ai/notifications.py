from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class NotificationMessage:
    channel: str
    subject: str
    body: str
    created_at: str


class Notifier(Protocol):
    def send(self, message: NotificationMessage) -> dict[str, str]:
        ...


class DryRunNotifier:
    """Default notifier used until email/LINE/app credentials are configured."""

    def send(self, message: NotificationMessage) -> dict[str, str]:
        return {
            "channel": message.channel,
            "status": "dry_run",
            "subject": message.subject,
            "created_at": message.created_at,
        }


class NotificationDispatcher:
    def __init__(self, notifier: Notifier | None = None):
        self.notifier = notifier or DryRunNotifier()

    def dispatch_signal(self, signal: dict, channel: str = "app") -> dict[str, str]:
        message = NotificationMessage(
            channel=channel,
            subject=f"{signal['symbol']} score {signal['score']}",
            body=(
                f"{signal['symbol']} stance={signal['stance']} "
                f"recommended={signal.get('recommended')} latest_close={signal['latest_close']}"
            ),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.notifier.send(message)
