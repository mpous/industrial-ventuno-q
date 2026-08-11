"""Edge inference service.

Subscribes to ``vibration/raw``, computes features (shared pipeline), scores the
window with the anomaly model, and publishes:
  * ``vibration/features``  - the feature summary
  * ``health/anomaly``      - score / threshold / verdict
  * ``health/state``        - healthy | anomaly  (never overrides 'maintenance')

Verdict requires the score to exceed the threshold for ``anomaly_persist``
consecutive windows, so a single noisy window does not raise an alarm.
"""
from __future__ import annotations

import time

import numpy as np

from ..config import CONFIG
from ..mqtt_client import MqttClient, now_ts
from .. import uns
from ..features import compute_features
from .models import build_model


class EdgeInference:
    def __init__(self, config=CONFIG):
        self.cfg = config
        self.mqtt = MqttClient(client_id="ventuno-inference")
        self.model = build_model(config.model_backend, config.eim_path)
        self._consecutive = 0
        self._current_state = uns.STATE_HEALTHY

    def start(self) -> None:
        self.mqtt.connect()
        self.mqtt.subscribe(uns.RAW, self._on_raw)
        self.mqtt.subscribe(uns.STATE, self._on_state)
        self.mqtt.publish(uns.STATE, {"state": uns.STATE_HEALTHY, "ts": now_ts()}, retain=True)

    def _on_state(self, topic: str, payload: dict) -> None:
        self._current_state = payload.get("state", self._current_state)

    def _on_raw(self, topic: str, payload: dict) -> None:
        axis = payload.get("axis", {})
        if not axis.get("x"):
            return
        fs = int(payload.get("fs_hz", self.cfg.sim_fs))
        summary, vec = compute_features(axis, fs)
        summary.update({"ts": now_ts()})
        self.mqtt.publish(uns.FEATURES, summary)

        score = float(self.model.score(vec, raw_axis=axis, fs=fs))
        threshold = self.cfg.anomaly_threshold
        over = score > threshold
        self._consecutive = self._consecutive + 1 if over else 0
        verdict = self._consecutive >= self.cfg.anomaly_persist

        self.mqtt.publish(
            uns.ANOMALY,
            {
                "ts": now_ts(),
                "anomaly_score": round(score, 4),
                "threshold": threshold,
                "verdict": verdict,
                "consecutive": self._consecutive,
                "model_ver": self.model.version,
            },
        )

        # Do not stomp a maintenance window; the corporate agent owns that state.
        if self._current_state != uns.STATE_MAINTENANCE:
            new_state = uns.STATE_ANOMALY if verdict else uns.STATE_HEALTHY
            if new_state != self._current_state:
                self._current_state = new_state
                self.mqtt.publish(uns.STATE, {"state": new_state, "ts": now_ts()}, retain=True)

    def stop(self) -> None:
        stop = getattr(self.model, "stop", None)
        if callable(stop):
            stop()
        self.mqtt.disconnect()


def main() -> None:
    svc = EdgeInference()
    svc.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        svc.stop()


if __name__ == "__main__":
    main()
