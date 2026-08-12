# PROMPTS log

A running log of the prompts driving this project, the reasoning behind each
change, and the result. Newest entries at the bottom. Append; don't rewrite
history.

---

## 2026-08-11 — Project kickoff & scope

**Prompt (paraphrased):** Build a machine-builder prototype for the Arduino
VENTUNO Q. Simulate conveyor-belt vibration in Python (no physical sensor),
detect anomalies with an Edge Impulse model, publish raw + inference data to a
Unified Namespace (MQTT), and have LLM-backed maintenance and planning agents
reason over the UNS and coordinate via the Google A2A protocol. Everything runs
on one board simulating a multi-layer Industry 5.0 enterprise stack.

**Reasoning / decisions:**
- Target is the **VENTUNO Q** (Qualcomm Dragonwing IQ8, 16 GB, Hexagon NPU) —
  *not* the UNO Q. Far more headroom: mid-size local LLM is feasible; no LED
  matrix (use HDMI/dashboard for status).
- Keep everything **pluggable** so it runs on a laptop with no ML/LLM deps:
  `MODEL_BACKEND=statistical` + `LLM_BACKEND=mock` for dev, board backends for
  production.
- **MQTT (Mosquitto)** = broadcast state/events on the UNS; **A2A** = directed
  task delegation between agents. Keep those two roles distinct.
- UNS = plain hierarchical ISA-95 JSON topics; on-device broker; one board
  simulates all enterprise layers.

**Result:** Full runnable scaffold under `ventuno/` (simulator, inference, kpi,
agents, dashboard) + `main.py` supervisor, `tools/export_dataset.py`, `app.yaml`,
`.env.example`, README. Self-closing demo loop:
healthy → anomaly → detect → maintenance → repaired → healthy.

---

## 2026-08-11 — 4-panel dashboard

**Prompt (paraphrased):** Split the dashboard into panels: (1) vibration +
real-time inference, with in-UI retraining via the Edge Impulse Data Ingestion
API using an API key; (2) live UNS viewer; (3) agents thinking in real-time with
their context and memory; (4) manufacturing KPIs — OEE, operational time,
operational cost, real-time production rate.

**Reasoning / decisions:**
- **Ingest only:** capture + label windows and push to Edge Impulse; retrain and
  build happen in EI Studio, then redeploy the `.eim`. The API key is read
  **server-side from env**, never exposed to the browser, never committed.
- Agent memory is **in-RAM session state** (rolling deque, resets on restart).
- KPIs are also published to the UNS (`kpi/*`) so agents can reason over them.
- Flask + Server-Sent Events; waveform downsampled to ~200 pts for the browser.

**Result:** `ventuno/dashboard/` with the 4 panels, `/api/ingest` (server-side
key), `/api/force_anomaly` demo trigger, and an SSE stream.

---

## 2026-08-11 — Version control

**Prompt:** Commit and push to `git@github.com:mpous/industrial-ventuno-q.git`;
then create a `dev` branch and push the code there.

**Reasoning / result:**
- `git init`, excluded `.env` and `.claude/` via `.gitignore`, initial commit of
  30 files on `main`.
- SSH port 22 was blocked and no SSH keys exist on the machine; switched the
  remote to **HTTPS** (works over 443 with the GitHub credential helper).
- Created `dev` and pushed — the full codebase now lives on `origin/dev`.

---

## 2026-08-11 — Adopt App Lab bricks (LLM + vibration anomaly)

**Prompt:** Check whether Arduino App Lab for the VENTUNO Q offers an LLM brick
(to call Gemma) and a vibration anomaly detection brick
(https://github.com/arduino/app-bricks-py/tree/main/src/arduino/app_bricks).
Change the application to use the bricks. Create this PROMPTS.md. Commit and push
to `dev`.

**Findings (from the app-bricks-py repo):** Both bricks exist —
- `llm` → `LargeLanguageModel`: `.chat()`, `.chat_stream()`, `.with_memory()`,
  configurable `system_prompt`/`temperature`; wraps LangChain over a local
  model (Gemma/Qwen), model selected/downloaded in App Lab.
- `vibration_anomaly_detection` → `VibrationAnomalyDetection`:
  `accumulate_samples()`, `on_anomaly(cb)`, `loop()`, `get_model_info()`
  (`.frequency`, `.input_features_count`); serves a deployed EI model via the
  App Lab EI runner. Raw anomaly score is a distance (can exceed 1.0).
- (Also present: `cloud_llm`, `vlm`, `visual_anomaly_detection`, `mqtt`, …)

**Reasoning / decisions:**
- Add each brick as a **third backend** rather than replacing the laptop paths,
  so `python main.py` still runs with `statistical` + `mock` and no Arduino deps.
  Brick imports are lazy (board-only).
- `LLM_BACKEND=brick` → `BrickLLM` wraps `LargeLanguageModel`. `complete()` folds
  system+user into one prompt (stateless per call; agents keep their own memory)
  and asks for a bare JSON object; a `_extract_json` helper strips prose/```json
  fences that a local model may add.
- `MODEL_BACKEND=brick` → `BrickModel` wraps `VibrationAnomalyDetection`. It
  ingests the raw window already published on `vibration/raw` (interleaved
  x,y,z), sets the brick threshold to 0 so `on_anomaly` fires every window,
  captures the latest score, and lets `edge_inference` apply its existing
  threshold + persistence logic. The raw distance is squashed with
  `tanh(score/3)` to match the pipeline's 0..1 scale (same as `EIModel`).
- `score()` signature widened to `score(vec, raw_axis=None, fs=None)` across all
  models; `edge_inference` passes the raw axis + fs through.
- `app.yaml` now declares `arduino:llm` and
  `arduino:vibration_anomaly_detection` so App Lab starts their backing services
  on the board. Declarations are ignored off-board.
- Docs (`README`, `.env.example`, `config.py` comments) updated with the `brick`
  options and an App-Lab-first "Run on the VENTUNO Q" path.

**Caveats (unverified):** This dev machine has no Python/Arduino tooling, so the
brick paths are written but **not executed**. Two assumptions to validate on
hardware: (1) the brick objects can be driven from our own supervisor threads
(calling `.loop()` / `.chat()`) without App Lab's `App.run()` owning the loop,
given App Lab has started the brick services; (2) the simulator's units/axis
order/sample rate match the deployed EI model's training data.

**Result:** `BrickLLM` + `BrickModel` added; `app.yaml` wires both bricks;
laptop defaults unchanged. Committed and pushed to `dev`.

---

## 2026-08-11 — App Lab upload rejected + broker connection refused

**Prompt:** App Lab upload fails with *"invalid app: bad request main python file
missing from app"*; after fixing, the app crashes at startup with
`ConnectionRefusedError: [Errno 111]`.

**Findings:**
- Current App Lab requires the entry point at **`python/main.py`** (and
  `requirements.txt` inside `python/`), not at the app root as older docs
  implied. Our root-level `main.py` was why App Lab reported it "missing".
- The startup crash is unrelated: the UNS needs a **Mosquitto broker** on
  `localhost:1883`, and none was running on the board, so the first agent's
  `connect()` was refused and `main.py` exited.

**Reasoning / decisions:**
- Moved `main.py`, `requirements.txt`, `ventuno/`, `tools/` under `python/`.
  Package imports still resolve (`ventuno` is a sibling of `main.py`).
- Hardened `config._load_dotenv()` to find `.env` in the cwd *or* the app root,
  since cwd is now ambiguous (repo root vs `python/` vs App Lab).
- Made `MqttClient.connect()` retry with backoff instead of hard-crashing, so
  app/broker startup order can't kill the demo, and raised a clear message
  pointing at `systemctl enable --now mosquitto`.
- README: hoisted the broker prerequisite to the top of the board section (it
  applies to *both* the brick and .eim/Ollama paths) and installed it as a
  systemd service; updated all run commands for the `python/` layout.

**Result:** App validates and starts under App Lab. Remaining board step is to
install/enable Mosquitto. Committed and pushed to `dev`.

---

## 2026-08-12 — App can't reach the broker from inside the App Lab container

**Prompt:** App still crashes on startup — 30 retries of
`ConnectionRefusedError: [Errno 111]` to `localhost:1883`, then exits — even
though Mosquitto is confirmed running on the board. "fix this".

**Findings / root cause:**
- The traceback paths (`/app/python/main.py`, `/app/.cache/.venv`) show App Lab
  runs the app in a **bridged container**. Inside it, `localhost` is the
  *container*, not the board, so the host's Mosquitto is unreachable at
  `localhost:1883`. The earlier connect-retry hardening only delayed the crash
  by 60s; the broker was genuinely unreachable at that address.
- Mosquitto's default config also binds only to `127.0.0.1` ("local only"), so
  even with the right host it wouldn't accept the container's connection.

**Reasoning / decisions:**
- **App side (code):** on a Docker bridge network the container's *default
  gateway* is the host (the board). Added `_default_gateway_ip()` (parses
  `/proc/net/route`) and `_candidate_hosts()`; `MqttClient.connect()` now tries
  the configured host first, then the gateway, then `172.17.0.1`, per retry
  round — so it self-heals under App Lab with no hardcoded board IP. Off-board
  (laptop) `localhost` still wins on the first try, so laptop dev is unchanged.
- **Board side (config, documented in README):** Mosquitto must listen beyond
  localhost. Add `/etc/mosquitto/conf.d/uns.conf` with `listener 1883 0.0.0.0` +
  `allow_anonymous true`, then `systemctl restart mosquitto`.

**Caveat (unverified):** written on the Windows dev box; not executed. Assumes
App Lab uses standard Docker bridge networking (gateway = host). If App Lab uses
host networking instead, `localhost` already works and the gateway fallback is
simply unused.

**Result:** `mqtt_client.py` gains gateway auto-discovery + multi-host connect;
README documents the `listener 0.0.0.0` prerequisite. Pending commit/push to
`dev`.
