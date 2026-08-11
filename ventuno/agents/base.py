"""Shared agent base: MQTT connection, rolling in-memory session memory, and
reasoning-trace publishing for dashboard Panel C.

Memory is intentionally in-RAM only (resets on restart), per the demo design.
"""
from __future__ import annotations

from collections import deque

from ..mqtt_client import MqttClient, now_ts
from .. import uns


class AgentBase:
    def __init__(self, name: str, memory_size: int = 20):
        self.name = name
        self.mqtt = MqttClient(client_id=f"ventuno-agent-{name}")
        self.memory: deque[dict] = deque(maxlen=memory_size)

    def connect(self) -> None:
        self.mqtt.connect()

    def remember(self, event: dict) -> None:
        event = {"ts": now_ts(), **event}
        self.memory.append(event)

    def publish_trace(self, event: str, context: dict, reasoning: str,
                      decision: dict | None = None) -> None:
        self.mqtt.publish(
            uns.agent_trace(self.name),
            {
                "ts": now_ts(),
                "agent": self.name,
                "event": event,
                "context": context,
                "reasoning": reasoning,
                "decision": decision or {},
                "memory": list(self.memory),
            },
        )
