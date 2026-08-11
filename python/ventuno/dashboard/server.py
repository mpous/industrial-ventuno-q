"""Operations dashboard (Flask + Server-Sent Events).

Subscribes to the whole UNS + agent traces, keeps the latest state, and streams
updates to the browser. Four panels:
  A - vibration & real-time inference (+ Edge Impulse ingest, server-side key)
  B - UNS live topic tree
  C - agents thinking (context, reasoning, memory) + A2A trace timeline
  D - manufacturing KPIs (OEE / time / cost / production)
"""
from __future__ import annotations

import json
import queue
import threading
import time

import requests
from flask import Flask, Response, jsonify, render_template, request

from ..config import CONFIG
from ..mqtt_client import MqttClient, now_ts
from .. import uns

app = Flask(__name__)

# Latest payload per topic (for initial render + Panel B tree).
_state: dict[str, dict] = {}
# Ring buffer of agent trace events (Panel C timeline).
_agent_events: list[dict] = []
# Last raw window (for Panel A waveform + EI ingestion).
_last_raw: dict = {}
# Connected SSE clients.
_subscribers: list[queue.Queue] = []
_lock = threading.Lock()

_mqtt = MqttClient(client_id="ventuno-dashboard")


def _broadcast(kind: str, topic: str, payload: dict) -> None:
    msg = json.dumps({"kind": kind, "topic": topic, "payload": payload, "ts": now_ts()})
    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _on_uns(topic: str, payload: dict) -> None:
    global _last_raw
    if topic == uns.RAW:
        _last_raw = payload
        # Downsample the waveform for the browser (don't ship 2000 pts/axis).
        axis = payload.get("axis", {})
        step = max(1, len(axis.get("x", [])) // 200)
        light = {
            "ts": payload.get("ts"),
            "fs_hz": payload.get("fs_hz"),
            "axis": {k: axis.get(k, [])[::step] for k in ("x", "y", "z")},
        }
        _broadcast("raw", topic, light)
        return
    _state[topic] = payload
    _broadcast("uns", topic, payload)


def _on_agent(topic: str, payload: dict) -> None:
    if not payload.get("agent"):  # ignore command/control topics under agents/
        return
    with _lock:
        _agent_events.append(payload)
        if len(_agent_events) > 100:
            del _agent_events[0]
    _broadcast("agent", topic, payload)


@app.route("/")
def index():
    return render_template("index.html", base=uns.BASE)


@app.route("/api/state")
def api_state():
    return jsonify({"uns": _state, "agents": _agent_events[-20:]})


@app.route("/api/force_anomaly", methods=["POST"])
def api_force_anomaly():
    """Panel A demo trigger: ask the simulator to inject a fault now."""
    fault = (request.json or {}).get("fault")
    _mqtt.publish("agents/dashboard/command", {"cmd": "force_anomaly", "fault": fault, "ts": now_ts()})
    return jsonify({"ok": True, "fault": fault})


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """Panel A retraining (ingest only): push the last raw window to Edge Impulse.

    The API key is read server-side from config/env and never exposed to the
    browser. Retraining/building happens in EI Studio afterwards.
    """
    if not CONFIG.ei_api_key:
        return jsonify({"ok": False, "error": "EI_API_KEY not set on server"}), 400
    if not _last_raw.get("axis"):
        return jsonify({"ok": False, "error": "no vibration window captured yet"}), 400

    label = (request.json or {}).get("label", "normal")
    axis = _last_raw["axis"]
    n = len(axis["x"])
    values = [[axis["x"][i], axis["y"][i], axis["z"][i]] for i in range(n)]
    fs = _last_raw.get("fs_hz", CONFIG.sim_fs)
    body = {
        "protected": {"ver": "v1", "alg": "none", "iat": int(time.time())},
        "signature": "0" * 64,
        "payload": {
            "device_name": "ventuno-conveyor",
            "device_type": "VENTUNO_Q",
            "interval_ms": 1000.0 / fs,
            "sensors": [
                {"name": "accX", "units": "g"},
                {"name": "accY", "units": "g"},
                {"name": "accZ", "units": "g"},
            ],
            "values": values,
        },
    }
    try:
        resp = requests.post(
            f"{CONFIG.ei_ingestion_url}/api/training/data",
            headers={
                "x-api-key": CONFIG.ei_api_key,
                "x-label": label,
                "x-file-name": f"{label}.{int(time.time())}.json",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=30,
        )
        return jsonify({"ok": resp.ok, "status": resp.status_code, "label": label, "body": resp.text[:200]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.route("/events")
def events():
    def stream():
        q: queue.Queue = queue.Queue(maxsize=200)
        with _lock:
            _subscribers.append(q)
        try:
            # Prime with current state so a fresh page isn't empty.
            for topic, payload in list(_state.items()):
                yield f"data: {json.dumps({'kind': 'uns', 'topic': topic, 'payload': payload})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)
    return Response(stream(), mimetype="text/event-stream")


def start_mqtt() -> None:
    _mqtt.connect()
    _mqtt.subscribe(uns.UNS_WILDCARD, _on_uns)
    _mqtt.subscribe(uns.AGENTS_WILDCARD, _on_agent)


def main() -> None:
    start_mqtt()
    app.run(host="0.0.0.0", port=CONFIG.dashboard_port, threaded=True)


if __name__ == "__main__":
    main()
