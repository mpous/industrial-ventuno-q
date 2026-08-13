# VENTUNO Q — Machine Intelligence Demo (Industry 5.0)

Edge **vibration anomaly detection** → **Unified Namespace (MQTT)** → **A2A agents**
(maintenance, planning, corporate) reasoning with a **local LLM** → a **4-panel
operations dashboard**. Everything runs on **one Arduino VENTUNO Q** simulating a
multi-layer enterprise stack — with laptop-development overrides (statistical
model + Ollama) for working without App Lab.

> Target board: **Arduino VENTUNO Q** (Qualcomm Dragonwing IQ8, 16 GB, Hexagon NPU).
> **Not** the Arduino UNO Q.

## The demo loop

```
healthy → simulator injects a fault (~every 5 min) → edge inference flags an
anomaly → published to the UNS → maintenance agent triages with the LLM →
work order → A2A call to corporate agent → maintenance window opens → machine
state = maintenance → planning agent re-plans production → KPIs (OEE/cost/rate)
react → window closes → machine repaired → healthy
```

## Architecture

| Layer | Component | Publishes / role |
|---|---|---|
| L0 Edge | `vibration_simulator` | `vibration/raw` (stands in for a CAN-FD/IEPE sensor) |
| L0 Edge | `edge_inference` | `vibration/features`, `health/anomaly`, `health/state` (statistical / EI `.eim` / `vibration_anomaly_detection` brick) |
| L1 UNS | Mosquitto | single source of truth / event bus |
| L2 | `maintenance_agent` (A2A + LLM) | `maintenance/workorder`, delegates via A2A |
| L4 | `corporate_agent` (A2A, mock CMMS) | `maintenance/window`, drives `health/state` |
| L3 | `planning_agent` (A2A + LLM) | `production/plan` |
| KPI | `kpi_service` | `kpi/oee`, `kpi/production`, `kpi/cost`, `kpi/uptime` |
| UX | `dashboard` (Flask :5001) | 4 panels, EI ingestion, "trigger anomaly" |

**MQTT** = broadcast state/events. **A2A** = directed task delegation between agents.

## UNS topic tree (ISA-95 by level)

Each datum is published at the enterprise level that owns it, not all under the
cell. Base cell path: `acme/barcelona/packaging/line1/conveyor01`.

```
acme/                                              (enterprise)
└─ barcelona/                                       (site)
   ├─ maintenance/workorder   {id, cause_hypothesis, severity, decision, rationale}
   ├─ maintenance/window (r)  {id, start, end, status}
   ├─ kpi/cost           (r)  {running_cost, downtime_cost, maintenance_cost, currency}
   ├─ agents/corporate/trace  (corporate/CMMS agent — site level)
   └─ packaging/                                    (area)
      └─ line1/                                      (line)
         ├─ production/plan       {plan_id, actions[], affected_orders[]}
         ├─ kpi/oee         (r)   {availability, performance, quality, oee}
         ├─ kpi/production  (r)   {rate_units_min, units_total, target_rate}
         ├─ kpi/uptime      (r)   {operational_time_s, downtime_s, state}
         ├─ agents/planning/trace (production-planning agent — line level)
         └─ conveyor01/                              (cell)
            ├─ vibration/raw          {ts, fs_hz, axis:{x,y,z}, rpm}
            ├─ vibration/features     {ts, rms, kurtosis, crest, band_energy[]}
            ├─ health/anomaly         {ts, anomaly_score, threshold, verdict, model_ver}
            ├─ health/model     (r)   {backend, version, ready, frequency, input_features, note}
            ├─ health/state     (r)   {state: healthy|anomaly|maintenance, ts}
            ├─ edge/status    (r,lwt) {online, app_ver}
            └─ agents/maintenance/trace (edge-maintenance agent — cell level)
```

Agent reasoning traces live **inside** the UNS at each agent's level (a compact
marker shows in the tree; the full context/reasoning/memory feeds dashboard
Panel C). The dashboard subscribes to the whole enterprise (`acme/#`).

## Run locally (laptop)

Prereqs: **Python 3.10+** and an **MQTT broker** on `localhost:1883`.

> App code lives under **`python/`** (App Lab requires `python/main.py`). Run
> from that folder.

```bash
# 1. MQTT broker (pick one)
#    native:  mosquitto
#    docker:  docker run -it -p 1883:1883 eclipse-mosquitto \
#             mosquitto -c /mosquitto-no-auth.conf

# 2. Python env
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r python/requirements.txt

# 3. Config (fast demo: lower the anomaly period)
cp .env.example .env               # loaded from the repo root or python/
#   set ANOMALY_PERIOD_S=45 for a quick loop

# 4. Run everything (one supervisor process)
cd python && python main.py
#   dashboard -> http://localhost:5001
```

Defaults now target the **VENTUNO Q under App Lab**: `MODEL_BACKEND=brick`
(the `vibration_anomaly_detection` brick serving your deployed Edge Impulse
model) and `LLM_BACKEND=brick` (the local `llm` brick — Gemma/Qwen/Qwen3). For
laptop development without App Lab, override in `.env`: set `MODEL_BACKEND=statistical`
and `LLM_BACKEND=ollama` (with a local Ollama server), or `eim` with a deployed
`.eim`. Click **Trigger anomaly** on Panel A to force the loop immediately.

### Run components individually (per-phase verification)

```bash
cd python
python -m ventuno.simulator.vibration_simulator
python -m ventuno.inference.edge_inference
python -m ventuno.kpi.kpi_service
python -m ventuno.agents.corporate_agent
python -m ventuno.agents.maintenance_agent
python -m ventuno.agents.planning_agent
python -m ventuno.dashboard.server
```

Verify:
```bash
# Watch the UNS
mosquitto_sub -t 'acme/#' -v
# Fetch an Agent Card (A2A)
curl http://localhost:8003/.well-known/agent-card.json
```

## Train the anomaly model (Edge Impulse)

```bash
# Generate a labeled dataset from the same physics model the simulator uses
cd python && python -m tools.export_dataset --per-class 60 --out dataset
```
1. Upload `dataset/` to Edge Impulse Studio.
2. Impulse: **Spectral Analysis (DSP)** + **Anomaly Detection (K-means)**.
3. Deploy → export **`.eim` for Arduino VENTUNO Q** (GPU/NPU where available).
4. Put it at `models/conveyor-anomaly.eim`, `chmod +x`, set `MODEL_BACKEND=eim`.

**Panel A retraining (ingest only):** enter your Edge Impulse API key in the
panel (kept in the browser, sent per request), pick a label, and use **Record
10s** to capture a live 10-second sample — or **Ingest 1 window** for a single
window — pushed via the Ingestion API. Retrain/build in EI Studio, then
re-deploy the `.eim` (or the vibration brick model).

## Run on the VENTUNO Q

**The UNS broker ships as a Custom Brick.** `bricks/mqtt_broker/` defines an
Eclipse Mosquitto container; under App Lab the orchestrator starts it alongside
the app on the same virtual Docker network. The app reaches it by the compose
service name — so set `MQTT_HOST=mqtt_broker` in `.env`. No `apt install`, no
`systemctl`, no `/etc/mosquitto` edits. The broker also publishes `1883` to the
board host so `mosquitto_sub -h localhost -t 'acme/#' -v` works for debugging.

> If a **system Mosquitto** is already enabled on the board it will hold port
> 1883 and clash with the brick — disable it first:
> `sudo systemctl disable --now mosquitto`.

Then pick a backend combo.

### A) App Lab bricks (recommended)

`app.yaml` declares three bricks App Lab starts for you: the custom
`mqtt_broker` (UNS), `arduino:llm` (local Gemma/Qwen) and
`arduino:vibration_anomaly_detection` (serves your deployed Edge Impulse model).
Select/download the LLM model in App Lab, deploy the vibration model, then:

```bash
cp .env.example .env
#   MQTT_HOST=mqtt_broker   MODEL_BACKEND=brick   LLM_BACKEND=brick
arduino-app-cli app start .
```

The `brick` backends ingest the same raw window we publish on `vibration/raw`
and call the same agent interface — no other code changes.

### B) Direct (.eim + Ollama, no App Lab)

Running `python main.py` directly means the App Lab orchestrator isn't there to
start the broker brick, so provide a broker yourself — either the same container
or a system Mosquitto:

```bash
# broker (pick one)
docker run -d --name uns -p 1883:1883 \
  -v "$PWD/bricks/mqtt_broker/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  eclipse-mosquitto:latest
#   or: sudo apt install -y mosquitto && sudo systemctl enable --now mosquitto

curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:4b                     # local LLM (Qwen is pre-bundled as a fallback)

cp .env.example .env
#   MQTT_HOST=localhost   MODEL_BACKEND=eim   LLM_BACKEND=ollama   OLLAMA_MODEL=gemma3:4b
cd python && python main.py
```
Open `http://<board-ip>:5001`.

> The app still auto-discovers the broker via the container's default gateway as
> a fallback (kept from before), but with the `mqtt_broker` brick the service
> name is the primary, reliable path.

## Configuration

All settings are environment variables (see `.env.example`): broker, UNS base,
sampling/anomaly cadence, model + LLM backends, agent ports, EI ingestion key.
