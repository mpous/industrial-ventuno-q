"""Corporate / business agent (mock CMMS/ERP).

A2A server exposing a ``schedule_inspection`` skill. On request it books an
inspection slot + maintenance window, publishes the window to the UNS, and
drives the machine into the MAINTENANCE state. A timer closes the window after
``maint_duration_s`` and returns the machine to HEALTHY (closing the demo loop).
"""
from __future__ import annotations

import json
import threading
import time
import uuid

from ..config import CONFIG
from ..mqtt_client import now_ts
from .. import uns
from .base import AgentBase
from .a2a import A2AServer


class CorporateAgent(AgentBase):
    def __init__(self, config=CONFIG):
        super().__init__("corporate")
        self.cfg = config
        self.server = A2AServer(
            name="Corporate Scheduling Agent",
            description="Mock CMMS/ERP that books maintenance inspections.",
            url=config.corp_url,
            skills=[{
                "id": "schedule_inspection",
                "name": "Schedule inspection",
                "description": "Book an inspection slot and open a maintenance window.",
                "tags": ["maintenance", "cmms", "erp"],
            }],
            handler=self._handle,
        )

    def start(self) -> None:
        self.connect()
        self.server.start(self.cfg.a2a_host, self.cfg.corp_port)
        print(f"[corporate] A2A card at {self.cfg.corp_url}/.well-known/agent-card.json")

    def _handle(self, text: str) -> str:
        try:
            wo = json.loads(text)
        except ValueError:
            wo = {"raw": text}

        window_id = f"MW-{uuid.uuid4().hex[:6]}"
        start = now_ts()
        end = start + self.cfg.maint_duration_s
        window = {"id": window_id, "start": start, "end": end, "status": "scheduled",
                  "workorder": wo.get("id"), "cause": wo.get("cause_hypothesis")}

        reasoning = (
            f"Received work order {wo.get('id')} (cause: {wo.get('cause_hypothesis')}, "
            f"severity: {wo.get('severity')}). Next technician slot available now; "
            f"opening a {int(self.cfg.maint_duration_s)}s maintenance window {window_id}."
        )
        self.remember({"event": "scheduled", "window_id": window_id, "workorder": wo.get("id")})
        self.publish_trace("schedule_inspection", {"workorder": wo}, reasoning, window)

        # Publish window + drive machine into maintenance.
        self.mqtt.publish(uns.WINDOW, window, retain=True)
        self.mqtt.publish(uns.STATE, {"state": uns.STATE_MAINTENANCE, "ts": now_ts()}, retain=True)

        threading.Thread(target=self._close_later, args=(window,), daemon=True).start()
        return json.dumps(window)

    def _close_later(self, window: dict) -> None:
        time.sleep(self.cfg.maint_duration_s)
        window = {**window, "status": "closed", "end": now_ts()}
        self.mqtt.publish(uns.WINDOW, window, retain=True)
        self.mqtt.publish(uns.STATE, {"state": uns.STATE_HEALTHY, "ts": now_ts()}, retain=True)
        self.remember({"event": "closed", "window_id": window["id"]})
        self.publish_trace("close_window", {"window_id": window["id"]},
                           "Maintenance window elapsed; inspection complete, returning machine to service.",
                           window)


def main() -> None:
    agent = CorporateAgent()
    agent.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
