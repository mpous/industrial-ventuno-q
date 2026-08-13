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

---

## 2026-08-12 — Dashboard feature round: EI recording, maintenance realism, model transparency, theming, UNS tree

**Prompt (paraphrased):** In the dashboard: (1) let me enter the EI API key in
the UI and *record* 10-second labeled samples to Edge Impulse; (2) make the
maintenance window ~1 minute so the machine is fixed in 60s and resumes — and
show *no* vibration while under maintenance; (3) is the anomaly score real from
the vibration_anomaly_detection brick? if so, show the model; (4) add a light
mode alongside night mode; (5) EI logo top-left + title "Industrial Automation
Project with UNS and Agents"; (6) render the UNS live view as an ISA-95 topic
tree. Ask questions first.

**Clarifying answers from the user:** EI key = **browser-only** (sent per
request, not stored server-side); Record = **10s live capture + dropdown
label**; maintenance = **machine stopped, flat/zero vibration, 60s repair**;
logo = **bundle locally**.

**Answer to (3):** With `MODEL_BACKEND=statistical` (the current run) the score
is the z-distance baseline, **not** the brick. Real brick inference needs
`MODEL_BACKEND=brick` + a deployed EI vibration model; only then does
`get_model_info()` (frequency, input_features_count) return real data.

**Reasoning / decisions:**
- **Model transparency:** new retained UNS topic `health/model`. Each model
  gained `info()`; `edge_inference` publishes it at startup. Panel A shows a
  LIVE-EI vs BASELINE badge so the demo is honest about what's actually running.
- **Maintenance realism:** `MAINT_DURATION_S` default 90→60. Simulator tracks
  `_under_maintenance` (from `health/state`) and emits flat zeros (rpm 0) during
  the repair window; `edge_inference` short-circuits to score 0 while in
  maintenance so the flat window isn't misread as an anomaly. Machine resumes
  healthy when the window closes.
- **EI record/ingest (browser key):** dropped the server-side `EI_API_KEY`
  dependency in the dashboard. `/api/ingest` and new `/api/record` take the key
  in the request body. `/api/record` buffers full-resolution raw windows
  server-side for N seconds (client shows a countdown), stitches them, and
  uploads one labeled sample. Key persists in browser `localStorage` only.
- **Theming:** CSS custom properties + `html[data-theme="light"]` overrides;
  header toggle persists the choice; default stays dark.
- **Branding:** EI logo downloaded to `dashboard/static/edge-impulse-logo.svg`
  (served locally, works offline) on a white badge (its wordmark is black, so
  the badge keeps it visible in dark mode). Title updated.
- **UNS tree:** Panel B now builds a nested `<details>` tree by splitting topics
  on `/`, reflecting the ISA-95 hierarchy instead of a flat list.

**Security note:** the user explicitly chose browser-held keys, overriding the
earlier server-side-only stance. The key is never committed and never persisted
on the board; it lives in the browser and is used only for the outbound EI call.

**Caveat (unverified):** written on the Windows dev box (no Python); not
executed. Brick model-info values only populate under the brick backend on
hardware.

**Result:** config, simulator, edge_inference, models, uns, dashboard
(server + template), README, `.env.example` updated; logo bundled. Pending
commit/push to `dev`.

---

## 2026-08-13 — UNS ISA-95 by level, dashboard layout, agent history + LLM badge, tooltips

**Prompt (paraphrased):** Agents and factory KPIs shouldn't all sit under the
conveyor/vibration topic — find a better place in the UNS hierarchy. Also: make
the UNS box larger and the KPI box smaller; show historical LLM agent messages
(scrollable); show which LLM agent is used; add a "?" next to each concept
(kurtosis, RMS, KPI, …) with a plain-language explainer.

**Design answers (from the user):** UNS layout = **ISA-95 by level**; viewer
scope = **whole enterprise `acme/#`**; agent traces = **inside the UNS at each
level**.

**Reasoning / decisions:**
- **`uns.py` now derives ISA-95 levels** by splitting the base path
  (`enterprise/site/area/line/cell`) and publishes each datum where it belongs:
  - **Cell** (conveyor01): `vibration/raw`, `vibration/features`,
    `health/anomaly`, `health/model`, `health/state`, `edge/status`.
  - **Line** (line1): `production/plan`, `kpi/oee`, `kpi/production`,
    `kpi/uptime` — a line is planned and measured as a unit.
  - **Site** (barcelona): `maintenance/workorder`, `maintenance/window`,
    `kpi/cost` — maintenance and cost are business functions above one machine.
  Because every service references `uns.*` constants, relocating the topics
  propagates with no changes to the simulator/inference/KPI/agent code.
- **Agent traces moved inside the UNS** at each agent's level
  (`{level}/agents/<name>/trace`): maintenance→cell, planning→line,
  corporate→site. `agent_trace()` maps the level; `ENTERPRISE_WILDCARD` (`acme/#`)
  now covers everything, so the dashboard uses a single subscription.
- **Dashboard server:** subscribes to `acme/#` only; `_on_uns` detects
  `…/trace` topics — routes the full event to Panel C and stores a *compact*
  marker (agent/event/decision/ts) in the tree so it isn't buried under the
  memory blob. The index route now passes a **named topic map** (`topics|tojson`)
  plus **LLM-in-use** info so the browser looks up topics by name instead of
  reconstructing `BASE + '/…'` (which would break now that topics live at
  different levels).
- **Layout:** CSS grid areas `"a b"/"c b"/"c d"` — UNS (B) and agent history (C)
  are tall, KPI (D) is a small box.
- **Panel C:** keeps a rolling 200-event history rendered newest-first with a
  timestamp; seeds from `/api/state` on load (SSE prime only carries UNS state).
  A badge shows the active LLM backend/model (mock / Ollama / App Lab brick).
- **Tooltips:** a `.tip` "?" marker (native `title`) next to anomaly score, RMS,
  kurtosis, crest, UNS, OEE, availability, performance, quality, rate, units,
  operational time, downtime, cost.

**Caveat (unverified):** written on the Windows dev box (no Python); not
executed. Grid proportions and the trace-in-tree rendering are best-effort.

**Result:** `uns.py`, `dashboard/server.py`, `dashboard/templates/index.html`,
README updated. Pending commit/push to `dev`.
