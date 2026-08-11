"""Thin wrapper around paho-mqtt (v1.x API) with JSON helpers and a Last-Will.

Pinned to paho-mqtt 1.6.x for stable v1 callback signatures across platforms.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable

import paho.mqtt.client as mqtt

from .config import CONFIG


class MqttClient:
    def __init__(self, client_id: str, lwt_topic: str | None = None, lwt_payload: dict | None = None):
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._handlers: dict[str, Callable[[str, dict], None]] = {}
        self._connected = threading.Event()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        if lwt_topic is not None:
            self._client.will_set(lwt_topic, json.dumps(lwt_payload or {"online": False}), qos=1, retain=True)

    # --- lifecycle ---
    def connect(self, timeout: float = 10.0, retries: int = 30, retry_delay: float = 2.0) -> None:
        """Connect to the broker, retrying if it isn't up yet.

        On the board the app and Mosquitto can start in either order, so a single
        refused connection shouldn't kill the demo. We retry the TCP connect for
        up to ``retries * retry_delay`` seconds before giving up.
        """
        host, port = CONFIG.mqtt_host, CONFIG.mqtt_port
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._client.connect(host, port, keepalive=30)
                break
            except (ConnectionRefusedError, OSError) as exc:
                last_exc = exc
                print(f"[mqtt] broker {host}:{port} unavailable ({exc}); "
                      f"retry {attempt}/{retries} in {retry_delay:.0f}s")
                time.sleep(retry_delay)
        else:
            raise ConnectionError(
                f"MQTT broker at {host}:{port} never came up. Start it, e.g. "
                f"`sudo systemctl enable --now mosquitto`."
            ) from last_exc
        self._client.loop_start()
        if not self._connected.wait(timeout):
            raise TimeoutError(f"MQTT connect timeout to {host}:{port}")

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    # --- pub/sub ---
    def publish(self, topic: str, payload: dict, retain: bool = False, qos: int = 0) -> None:
        self._client.publish(topic, json.dumps(payload, default=str), qos=qos, retain=retain)

    def subscribe(self, topic: str, handler: Callable[[str, dict], None], qos: int = 0) -> None:
        self._handlers[topic] = handler
        if self._connected.is_set():
            self._client.subscribe(topic, qos=qos)

    # --- callbacks ---
    def _on_connect(self, client, userdata, flags, rc):
        self._connected.set()
        for topic in self._handlers:
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {"_raw": msg.payload.decode("utf-8", errors="replace")}
        for pattern, handler in self._handlers.items():
            if mqtt.topic_matches_sub(pattern, msg.topic):
                try:
                    handler(msg.topic, payload)
                except Exception as exc:  # keep the loop alive on handler errors
                    print(f"[mqtt] handler error on {msg.topic}: {exc}")


def now_ts() -> float:
    return time.time()
