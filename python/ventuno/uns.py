"""Unified Namespace topic contract (single source of truth).

Plain hierarchical ISA-95 topics under a configurable base path
(enterprise/site/area/line/cell). All payloads are JSON.

Agent reasoning traces are intentionally NOT under the UNS base path: they are
demo telemetry for the dashboard, published under ``agents/`` so the UNS tree
stays clean (state + events only).
"""
from __future__ import annotations

from .config import CONFIG

BASE = CONFIG.uns_base

# --- Edge / machine ---
RAW = f"{BASE}/vibration/raw"                 # {ts, fs_hz, axis:{x[],y[],z[]}, rpm}
FEATURES = f"{BASE}/vibration/features"       # {ts, rms, kurtosis, crest, band_energy[]}
ANOMALY = f"{BASE}/health/anomaly"            # {ts, anomaly_score, threshold, verdict, model_ver}
MODEL = f"{BASE}/health/model"                # retained {backend, version, ready, frequency, input_features, note}
STATE = f"{BASE}/health/state"                # retained {state, ts}
EDGE_STATUS = f"{BASE}/edge/status"           # retained + LWT {online, app_ver}

# --- Maintenance / business ---
WORKORDER = f"{BASE}/maintenance/workorder"   # {id, cause_hypothesis, severity, decision, rationale, ts}
WINDOW = f"{BASE}/maintenance/window"         # retained {id, start, end, status}
PLAN = f"{BASE}/production/plan"              # {plan_id, actions[], affected_orders[], ts}

# --- KPIs ---
KPI_OEE = f"{BASE}/kpi/oee"                   # retained {availability, performance, quality, oee, ts}
KPI_PRODUCTION = f"{BASE}/kpi/production"     # retained {rate_units_min, units_total, target_rate, ts}
KPI_COST = f"{BASE}/kpi/cost"                 # retained {running_cost, downtime_cost, maintenance_cost, currency, ts}
KPI_UPTIME = f"{BASE}/kpi/uptime"             # retained {operational_time_s, downtime_s, state, ts}

# --- Optional vision ---
VISION = f"{BASE}/vision/inspection"          # {ts, defect, confidence, bbox[]}

# --- Agent reasoning traces (dashboard telemetry, not UNS) ---
def agent_trace(name: str) -> str:
    return f"agents/{name}/trace"

AGENTS_WILDCARD = "agents/#"
UNS_WILDCARD = f"{BASE}/#"

# States used on STATE topic
STATE_HEALTHY = "healthy"
STATE_ANOMALY = "anomaly"
STATE_MAINTENANCE = "maintenance"
