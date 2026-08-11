"""Pluggable LLM backend for the agents.

* MockLLM   - deterministic, dependency-free reasoning used on a laptop and as a
  demo-safe fallback. Returns strict JSON so agents parse reliably, plus a short
  natural-language reasoning trace for Panel C.
* OllamaLLM - talks to a local Ollama server running Gemma (or Qwen) on the
  VENTUNO Q. Uses the /api/chat endpoint with format=json.
* BrickLLM  - uses the Arduino App Lab ``llm`` brick (LargeLanguageModel) to run
  a local model (Gemma/Qwen) on the VENTUNO Q. Board-only: the model is selected
  and downloaded in App Lab; the brick's backing service is started by App Lab.

All expose: complete(system, user, want_json=True) -> (text, reasoning).
"""
from __future__ import annotations

import json

import requests

from ..config import CONFIG


def _extract_json(text: str) -> str:
    """Best-effort: pull the first {...} object out of a chatty LLM reply.

    Local models sometimes wrap JSON in prose or a ```json fence; the agents need
    a bare object to parse.
    """
    if not text:
        return "{}"
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1:]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return t[start:end + 1]
    return t


class MockLLM:
    name = "mock"

    def complete(self, system: str, user: str, want_json: bool = True) -> tuple[str, str]:
        ctx = {}
        try:
            ctx = json.loads(user)
        except ValueError:
            pass

        # Maintenance triage heuristic
        if "anomaly_score" in ctx:
            score = float(ctx.get("anomaly_score", 0))
            persist = int(ctx.get("consecutive", 0))
            fault = ctx.get("suspected_fault", "unknown")
            severe = score >= 0.75 or persist >= 5
            decision = "repair" if severe else ("repair" if score >= 0.6 else "false_alarm")
            reasoning = (
                f"Anomaly score {score:.2f} over threshold for {persist} consecutive windows. "
                f"Spectral signature consistent with '{fault}'. "
                + ("Sustained high-energy fault -> schedule inspection." if decision == "repair"
                   else "Low persistence / borderline score -> likely transient, mark false alarm.")
            )
            out = {
                "decision": decision,
                "cause_hypothesis": fault,
                "severity": "high" if severe else ("medium" if decision == "repair" else "low"),
                "rationale": reasoning,
            }
            return json.dumps(out), reasoning

        # Planning heuristic
        if "maintenance_window" in ctx:
            oee = float(ctx.get("oee", 0.0))
            reasoning = (
                f"Machine entering maintenance window; current OEE {oee:.2f}. "
                "Rerouting affected orders to Line 2 and throttling upstream buffer to avoid pile-up."
            )
            out = {
                "plan_id": f"plan-{ctx.get('window_id', 'x')}",
                "actions": [
                    "reroute affected orders to line2",
                    "throttle upstream feed to 60%",
                    "notify shift supervisor",
                ],
                "affected_orders": ctx.get("affected_orders", ["WO-1001", "WO-1002"]),
            }
            return json.dumps(out), reasoning

        return json.dumps({"note": "no-op"}), "No actionable context."


class OllamaLLM:
    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"

    def complete(self, system: str, user: str, want_json: bool = True) -> tuple[str, str]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if want_json:
            body["format"] = "json"
        resp = requests.post(f"{self.host}/api/chat", json=body, timeout=120)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "").strip()
        reasoning = ""
        try:
            reasoning = json.loads(content).get("rationale", "")
        except ValueError:
            reasoning = content[:400]
        return content, reasoning


class BrickLLM:
    """Local LLM via the App Lab ``llm`` brick (LargeLanguageModel).

    Board-only. The brick wraps LangChain over a locally-hosted model (default
    depends on the board; Gemma/Qwen selectable in App Lab). We combine the
    system + user text into one prompt because ``complete()`` is stateless per
    call and the agents already carry their own rolling memory.
    """

    def __init__(self, model: str | None = None):
        from arduino.app_bricks.llm import LargeLanguageModel  # board-only import

        self._llm = LargeLanguageModel()
        self.name = f"brick-llm:{model or 'default'}"

    def complete(self, system: str, user: str, want_json: bool = True) -> tuple[str, str]:
        prompt = f"{system}\n\n{user}"
        if want_json:
            prompt += "\n\nRespond with ONLY a single JSON object, no prose."
        text = self._llm.chat(prompt)
        content = _extract_json(text) if want_json else text
        try:
            reasoning = json.loads(content).get("rationale", "")
        except ValueError:
            reasoning = (text or "")[:400]
        return content, reasoning


def build_llm():
    if CONFIG.llm_backend == "brick":
        return BrickLLM(CONFIG.ollama_model)
    if CONFIG.llm_backend == "ollama":
        return OllamaLLM(CONFIG.ollama_host, CONFIG.ollama_model)
    return MockLLM()
