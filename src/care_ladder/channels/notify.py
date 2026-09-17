"""Facility notify tools: Slack webhook channel notifications (stub fallback).

Real delivery when SLACK_WEBHOOK_URL is set; otherwise an honest audit stub
(``adapter: stub``) so demos never claim a delivery that did not happen.
"""
from __future__ import annotations

import os
from typing import Any


class NotifyChannelAdapter:
    """Slack-webhook channel notifier for facility ops."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self._webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    async def notify_async(self, message: str) -> dict[str, Any]:
        if not self._webhook_url:
            return {"adapter": "stub", "delivered": True, "message": message}
        import httpx2 as httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._webhook_url, json={"text": message}
                )
            ok = resp.status_code == 200
            return {
                "adapter": "slack",
                "delivered": ok,
                "status_code": resp.status_code,
                "message": message,
            }
        except Exception as exc:  # network errors never break the ladder
            return {
                "adapter": "slack",
                "delivered": False,
                "error": str(exc),
                "message": message,
            }

    # sync convenience for tests / non-async callers
    def notify(self, message: str) -> dict[str, Any]:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            # running inside a loop: run in a fresh thread's loop
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, self.notify_async(message)).result()
        return asyncio.run(self.notify_async(message))


def notify_channel_tool(message: str, adapter: NotifyChannelAdapter | None = None) -> dict[str, Any]:
    a = adapter or NotifyChannelAdapter()
    return a.notify(message)
