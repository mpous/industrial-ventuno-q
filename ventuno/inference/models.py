"""Pluggable anomaly models.

* StatisticalModel  - dependency-free baseline. Learns feature mean/std during a
  healthy warm-up, then scores windows by mean z-distance mapped to 0..1.
  Stands in for the Edge Impulse model so the whole demo runs on a laptop.
* EIModel           - runs a real Edge Impulse ``.eim`` (Spectral Analysis +
  K-means anomaly detection) via ``edge_impulse_linux``. Used on the VENTUNO Q.

Both expose: score(feature_vector) -> float in [0, 1], and a ``version`` string.
"""
from __future__ import annotations

import numpy as np


class StatisticalModel:
    version = "statistical-0.1"

    def __init__(self, warmup: int = 20):
        self.warmup = warmup
        self._samples: list[np.ndarray] = []
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self.ready = False

    def score(self, vec: np.ndarray) -> float:
        if not self.ready:
            self._samples.append(vec)
            if len(self._samples) >= self.warmup:
                arr = np.asarray(self._samples)
                self._mean = arr.mean(axis=0)
                self._std = arr.std(axis=0) + 1e-6
                self.ready = True
            return 0.0
        z = np.abs((vec - self._mean) / self._std)
        return float(np.tanh(np.mean(z) / 3.0))


class EIModel:
    version = "eim"

    def __init__(self, model_path: str):
        from edge_impulse_linux.runner import ImpulseRunner  # imported lazily (board only)

        self._runner = ImpulseRunner(model_path)
        info = self._runner.init()
        self.version = f"eim:{info.get('project', {}).get('name', 'model')}"

    def score(self, vec: np.ndarray) -> float:
        res = self._runner.classify(vec.tolist())
        result = res.get("result", {})
        # K-means anomaly detection returns an "anomaly" score (higher = worse).
        anomaly = result.get("anomaly")
        if anomaly is not None:
            return float(np.tanh(float(anomaly) / 3.0))
        # Fallback: 1 - P(normal) if a classifier head is present.
        classification = result.get("classification", {})
        if classification:
            return float(1.0 - classification.get("normal", 0.0))
        return 0.0

    def stop(self) -> None:
        try:
            self._runner.stop()
        except Exception:
            pass


def build_model(backend: str, eim_path: str):
    if backend == "eim":
        return EIModel(eim_path)
    return StatisticalModel()
