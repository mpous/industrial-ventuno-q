# VENTUNO Q — Machine Intelligence Demo (Industry 5.0)

Edge **vibration anomaly detection** → **Unified Namespace (MQTT)** → **A2A agents**
(maintenance, planning, corporate) reasoning with a **local LLM** → a **4-panel
operations dashboard**. Everything runs on **one Arduino VENTUNO Q** simulating a
multi-layer enterprise stack — and also runs on a laptop for development (mock LLM
+ statistical anomaly model).

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

## UNS topic tree

Base: `acme/barcelona/packaging/line1/conveyor01`

```
vibration/raw            {ts, fs_hz, axis:{x,y,z}, rpm}
vibration/features       {ts, rms, kurtosis, crest, band_energy[]}
health/anomaly           {ts, anomaly_score, threshold, verdict, model_ver}
health/state       (r)   {state: healthy|anomaly|maintenance, ts}
edge/status      (r,lwt) {online, app_ver}
maintenance/workorder    {id, cause_hypothesis, severity, decision, rationale}
maintenance/window (r)   {id, start, end, status}
production/plan          {plan_id, actions[], affected_orders[]}
kpi/oee            (r)   {availability, performance, quality, oee}
kpi/production     (r)   {rate_units_min, units_total, target_rate}
kpi/cost           (r)   {running_cost, downtime_cost, maintenance_cost, currency}
kpi/uptime         (r)   {operational_time_s, downtime_s, state}
```
Agent reasoning traces are published under `agents/<name>/trace` (dashboard telemetry, not UNS).

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

Defaults are laptop-safe: `MODEL_BACKEND=statistical`, `LLM_BACKEND=mock` — no
Edge Impulse model or Ollama needed. Click **Trigger anomaly** on Panel A to
force the loop immediately.

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

**Panel A retraining (ingest only):** set `EI_API_KEY` (server-side) and use the
*Ingest window to Edge Impulse* button to push labeled windows via the Ingestion
API. Retrain/build in EI Studio, then re-deploy the `.eim`.

## Run on the VENTUNO Q

**Prerequisite (both paths): the UNS broker must be running _and reachable from
the app_.** App Lab runs the app in a bridged container, so `localhost` inside
the app is the container — not the board. Two things are needed: (1) Mosquitto
running, and (2) Mosquitto listening beyond `127.0.0.1` so the container can
reach it over the bridge. The app auto-discovers the board via the container's
default gateway, so you don't need to hardcode an IP.

```bash
ssh arduino@<board-ip>
sudo apt update && sudo apt install -y mosquitto mosquitto-clients

# Open the broker to the bridge network (default config is localhost-only).
sudo tee /etc/mosquitto/conf.d/uns.conf >/dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF

sudo systemctl enable --now mosquitto        # starts now + on every boot
sudo systemctl restart mosquitto             # pick up the new listener
systemctl is-active mosquitto                # -> active
mosquitto_sub -t 'acme/#' -v &               # optional: watch the UNS
```

> If Mosquitto stays on `localhost` only, the app fails all connect retries with
> `ConnectionRefusedError: [Errno 111]` and exits — the `listener 0.0.0.0` line
> is what fixes it. `allow_anonymous true` is fine for this on-board demo; add
> auth if the board is on an untrusted network.

Then pick a backend combo.

### A) App Lab bricks (recommended)

`app.yaml` declares two bricks that App Lab starts for you:
`arduino:llm` (local Gemma/Qwen) and `arduino:vibration_anomaly_detection`
(serves your deployed Edge Impulse model). Select/download the LLM model in App
Lab, deploy the vibration model, then:

```bash
cp .env.example .env
#   MODEL_BACKEND=brick   LLM_BACKEND=brick
arduino-app-cli app start .
```

The `brick` backends ingest the same raw window we publish on `vibration/raw`
and call the same agent interface — no other code changes.

### B) Direct (.eim + Ollama)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:4b                     # local LLM (Qwen is pre-bundled as a fallback)

cp .env.example .env
#   MODEL_BACKEND=eim   LLM_BACKEND=ollama   OLLAMA_MODEL=gemma3:4b
cd python && python main.py
```
Open `http://<board-ip>:5001`.

## Configuration

All settings are environment variables (see `.env.example`): broker, UNS base,
sampling/anomaly cadence, model + LLM backends, agent ports, EI ingestion key.
