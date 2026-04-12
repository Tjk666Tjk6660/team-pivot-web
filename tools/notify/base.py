"""Notifier interface."""
from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    """Abstract interface for sending notifications."""

    def send_card(
        self,
        *,
        title: str,
        summary: str,
        thread_url: str,
        author: str,
    ) -> bool:
        """Send a notification card. Returns True on success."""
        ...
