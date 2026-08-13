# Industrial Automation: Vibration Anomaly Detection using Edge Impulse with a Unified Namespace and AI agents on Arduino VENTUNO Q

## Project Description

This project turns a single **Arduino Ventuno Q** into a self-contained
**Industry 5.0** demo for machine builders: an industrial machine that detects
its own faults, reasons about them with on-device AI, and coordinates a repair —
all happening in the edge.

We use the **Vibration Anomaly Detection brick** (an Edge Impulse model) in
Arduino App Lab to watch a conveyor's vibration signature, and the **LLM brick**
(a local Gemma/Qwen model) to give a team of software agents the ability to
think. The agents talk to each other over Google's **Agent-to-Agent (A2A)**
protocol and share machine state through a **Unified Namespace (UNS)** — a single
source of truth based on MQTT hierarchy topic that is the real-time source of truth for the whole enterprise.

A typical machine ships with alarms and thresholds but no autonomy. We add edge
AI and agents, which give the machine a reason to act on its own. The demo runs a
self-closing loop:

- Detects an anomaly in the vibration signal,
- Triages it with a local LLM to decide *repair* vs. *false alarm*,
- Opens a maintenance window and re-plans production, then
- Repairs, recovers, and returns to healthy — while KPIs react live.

## Hardware Lineup

| Component | Notes | Link |
|---|---|---|
| Arduino Ventuno Q | Main compute — Qualcomm Dragonwing IQ8, 16 GB RAM, Hexagon NPU (MPU + MCU) | https://www.arduino.cc/product-ventuno-q/ |
| Vibration sensor (CAN-FD / IEPE accelerometer) | Optional — the demo *simulates* conveyor vibration in software; in production a sensor would ride the board's CAN-FD or analog inputs | *TBD* |
| HDMI display or any LAN device with a browser | To view the 4-panel operations dashboard | — |

> No physical machine or sensor is required to run the demo: a Python simulator
> generates a realistic conveyor vibration signature and injects faults, so the
> whole pipeline runs on one board out of the box.

## User Interface & Feedback

The user interacts with the system through a **4-panel web dashboard** (served by
the app on port `5001`, open in any browser on the LAN):

1. **Vibration & real-time inference** — live waveform, spectral features, anomaly
   score vs. threshold, and the current model (with in-UI Edge Impulse data
   ingestion to retrain the model).
2. **Unified Namespace** — the live ISA-95 topic tree updating in real time.
3. **Agents thinking** — each agent's context, LLM reasoning trace, decisions and
   rolling memory, plus the A2A message trace.
4. **Manufacturing KPIs** — OEE, availability/performance/quality, production rate,
   operational time and cost.

A **Trigger anomaly** button forces the loop immediately for live demos.

## The AI Model

- **Model used:** Edge Impulse vibration anomaly detection (Spectral Analysis DSP
  + K-means anomaly detection), served on-device by the App Lab
  `vibration_anomaly_detection` brick. A local LLM (Gemma / Qwen3) served by the
  App Lab `llm` brick powers the agents' reasoning.
- **Why:** K-means spectral anomaly detection is ideal for machine health — it
  learns the *healthy* vibration signature and flags any deviation, with no
  labeled fault data required. Keeping the LLM on the board (no cloud) is the
  Industry 5.0 promise: private, low-latency, resilient reasoning at the machine.
- **How:** Raw 3-axis vibration windows are turned into spectral features and
  scored as a distance from the healthy baseline. A threshold plus a persistence
  check (N consecutive windows) produces a verdict, which is published to the UNS.
  A **maintenance agent** reads that, reasons with the LLM to decide *repair* vs.
  *false alarm*, and — if real — delegates via A2A to a **corporate agent** that
  opens a maintenance window. A **planning agent** sees the window and re-plans
  production, and KPIs recompute across the whole cycle.

## Software Architecture

Everything runs on **one Ventuno Q**, simulating a multi-layer enterprise stack.
A Python app on the **MPU** runs several cooperating services; the **UNS broker**
and the **AI models** are provided by Arduino App Lab bricks.

```
Ventuno Q MPU (Python app)
 ├─ Vibration simulator ──► publishes raw vibration
 ├─ Edge inference (vibration_anomaly_detection brick) ──► anomaly score + verdict
 ├─ KPI service ──► OEE / production / cost
 ├─ Maintenance · Planning · Corporate agents (llm brick + A2A)
 └─ 4-panel dashboard (Flask, :5001)
        │  all state flows over MQTT
        ▼
Unified Namespace  ── mqtt_broker custom brick (Eclipse Mosquitto)
```

- **MQTT / UNS** is the broadcast layer: every service publishes and subscribes to
  a shared ISA-95 topic tree (`enterprise / site / area / line / cell`), so state
  and events are the single source of truth.
- **A2A** is the directed layer: agents delegate concrete tasks to one another
  (e.g. maintenance → corporate to schedule an inspection).
- The two roles are kept distinct: MQTT for *state*, A2A for *tasks*.

### The UNS broker as a Custom Brick

The Mosquitto broker ships as a **custom brick** (`bricks/mqtt_broker/`). Under
App Lab the orchestrator starts it alongside the app on the same virtual Docker
network, so the app reaches it by the compose service name — hostname
`mqtt_broker:1883`. The client also tries this name automatically, so no manual
broker install or `.env` edit is required.

### Pluggable backends

Every AI capability sits behind a pluggable interface, so the same code runs on a
laptop for development (statistical anomaly model + Ollama) and on the Ventuno Q
in production (App Lab bricks). The default targets the board.

## Visual and Media

*Videos and screenshots of the dashboard and the anomaly → repair loop to be
collected.*

## GitHub Repository Link
https://github.com/mpous/industrial-ventuno-q
