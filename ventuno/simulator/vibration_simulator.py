"""Vibration simulator service.

Streams 3-axis conveyor vibration windows to the UNS ``vibration/raw`` topic in
real time. Injects a random fault on average every ``anomaly_period_s`` seconds.
Subscribes to ``health/state``: when the machine enters MAINTENANCE it clears
the active fault (the machine has been repaired), which closes the demo loop:

    healthy -> anomaly injected -> detected -> maintenance -> repaired -> healthy
"""
from __future__ import annotations

import threading
import time

from ..config import CONFIG
from ..mqtt_client import MqttClient, now_ts
from .. import uns
from .conveyor import ConveyorModel, FAULT_MODES


class VibrationSimulator:
    def __init__(self, config=CONFIG):
        self.cfg = config
        self.model = ConveyorModel(fs=config.sim_fs, rpm=config.sim_rpm)
        self.mqtt = MqttClient(client_id="ventuno-simulator")
        self.rng = self.model.rng
        self._active_fault: str | None = None
        self._severity: float = 1.0
        self._next_anomaly_at = time.monotonic() + self._sample_interval()
        self._force = threading.Event()
        self._forced_fault: str | None = None
        self._stop = threading.Event()

    def _sample_interval(self) -> float:
        # Poisson-like arrival around the configured mean period.
        return max(20.0, self.rng.exponential(self.cfg.anomaly_period_s))

    def force_anomaly(self, fault: str | None = None) -> None:
        """Deterministic trigger for live demos (called by the dashboard)."""
        self._forced_fault = fault
        self._force.set()

    def _on_state(self, topic: str, payload: dict) -> None:
        if payload.get("state") == uns.STATE_MAINTENANCE and self._active_fault:
            print(f"[sim] maintenance -> clearing fault '{self._active_fault}' (repaired)")
            self._active_fault = None
            self._next_anomaly_at = time.monotonic() + self._sample_interval()

    def _maybe_trigger(self) -> None:
        if self._active_fault is not None:
            return
        if self._force.is_set():
            self._force.clear()
            fault = self._forced_fault or self.rng.choice(FAULT_MODES)
            self._begin_fault(str(fault))
        elif time.monotonic() >= self._next_anomaly_at:
            self._begin_fault(str(self.rng.choice(FAULT_MODES)))

    def _begin_fault(self, fault: str) -> None:
        self._active_fault = fault
        self._severity = float(self.rng.uniform(0.7, 1.3))
        print(f"[sim] injecting fault '{fault}' severity={self._severity:.2f}")

    def start(self) -> None:
        self.mqtt.connect()
        self.mqtt.subscribe(uns.STATE, self._on_state)
        self.mqtt.subscribe("agents/dashboard/command", self._on_command)
        self.mqtt.publish(uns.EDGE_STATUS, {"online": True, "app_ver": "0.1.0", "ts": now_ts()}, retain=True)
        thread = threading.Thread(target=self._run, name="simulator", daemon=True)
        thread.start()

    def _on_command(self, topic: str, payload: dict) -> None:
        if payload.get("cmd") == "force_anomaly":
            self.force_anomaly(payload.get("fault"))

    def _run(self) -> None:
        n = self.cfg.sim_window
        fs = self.cfg.sim_fs
        window_period = n / fs  # real-time cadence
        while not self._stop.is_set():
            t0 = time.monotonic()
            self._maybe_trigger()
            win = self.model.generate_window(n, fault=self._active_fault, severity=self._severity)
            self.mqtt.publish(
                uns.RAW,
                {
                    "ts": now_ts(),
                    "fs_hz": fs,
                    "rpm": self.cfg.sim_rpm,
                    "axis": {k: [round(v, 5) for v in win[k].tolist()] for k in ("x", "y", "z")},
                    "_label": self._active_fault or "normal",  # ground truth for dataset export
                },
            )
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, window_period - elapsed))

    def stop(self) -> None:
        self._stop.set()
        self.mqtt.publish(uns.EDGE_STATUS, {"online": False, "app_ver": "0.1.0", "ts": now_ts()}, retain=True)
        self.mqtt.disconnect()


def main() -> None:
    sim = VibrationSimulator()
    sim.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()
