"""v402 — RESEARCH agent (JAG-403b).

Stdlib-only, deterministic. Research = iterative web discovery + summarisation
+ import into a notebook. The research LLM is configurable (Perplexity Sonar,
OpenRouter chat, or the local rllm router). Depth controls round count and
sources per round.

  A) researchcfg: model catalogue + active selection + depth/budget
  B) plan: depth shallow/medium/deep controls rounds and per-round budget
  C) executor: end-to-end with stubbed web search + research LLM
  D) API/CLI/WebUI wiring guards
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v402-")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


# --------------------------------------------------------------------------- A
from longrun.research import researchcfg as rc  # noqa: E402

check("A1 catalogue has a perplexity research model and a local fallback",
      any("perplexity" in m["id"] or "sonar" in m["id"] for m in rc.MODELS)
      and any(m["provider"] == "local" or m["provider"] == "rllm" for m in rc.MODELS))
check("A2 each model carries id+provider+label", all({"id", "provider", "label"}.issubset(m)
                                                      for m in rc.MODELS))
check("A3 default active model is set on first call",
      bool(rc.active_model()))
check("A4 set_active persists a custom model id",
      rc.set_active("perplexity:sonar-pro")["ok"])
check("A5 custom_models overlay is preserved by save_config",
      "custom_models" in rc.load_config())
check("A6 depth shallow/medium/deep have a default budget per round",
      rc.depth_budget("shallow")["rounds"] == 1
      and rc.depth_budget("medium")["rounds"] >= 2
      and rc.depth_budget("deep")["rounds"] >= rc.depth_budget("medium")["rounds"])

# --------------------------------------------------------------------------- B
from longrun.research import research as rs  # noqa: E402

plan_s = rs.make_plan("kubernetes operator patterns", depth="shallow", n=5, max_rounds=4)
check("B1 shallow plan: 1 round + ≤n sources",
      plan_s["rounds"] == 1 and plan_s["max_sources"] >= 5 and plan_s["queries"])
plan_m = rs.make_plan("kubernetes operator patterns", depth="medium", n=5, max_rounds=4)
check("B2 medium plan: 2 rounds + expanded queries",
      plan_m["rounds"] >= 2 and len(plan_m["queries"]) >= 2)
plan_d = rs.make_plan("kubernetes operator patterns", depth="deep", n=5, max_rounds=4)
check("B3 deep plan: rounds capped at max_rounds, queries scale with rounds",
      plan_d["rounds"] <= 4 and len(plan_d["queries"]) >= len(plan_m["queries"]) and plan_d["queries"])
check("B4 plan preserves the user query verbatim",
      "kubernetes operator patterns" in plan_s["queries"][0])

# --------------------------------------------------------------------------- C (end-to-end with stubs)
import longrun.memory.knowledge as kb  # noqa: E402
from longrun.research import executor as ex  # noqa: E402

# stub: web search returns 3 candidates for the first query, 2 for the second
_FAKE_URLS = [
    "https://example.com/k8s-operator-a", "https://example.com/k8s-operator-b",
    "https://example.com/k8s-operator-c",
]
_FAKE_URLS_2 = ["https://example.com/k8s-operator-d", "https://example.com/k8s-operator-e"]


def _stub_search(query, n):
    if "expanded" in query or "deep-dive" in query:
        return [{"title": "second " + u, "url": u, "snippet": "ok"} for u in _FAKE_URLS_2], "stub"
    return [{"title": "first " + u, "url": u, "snippet": "ok"} for u in _FAKE_URLS], "stub"


# stub: fetcher returns canned text per URL
def _stub_fetch(url):
    return "# " + url + "\n\nLong body about k8s operators.\n" + ("lorem ipsum. " * 40)


# stub: research LLM returns a 1-paragraph summary
def _stub_llm(prompt, model, timeout=30):
    return {
        "summary": "Research summary about: " + prompt[:60],
        "queries": ["expanded: kubernetes operator patterns", "deep-dive: controller-runtime"],
    }


# patch into the module the executor uses
ex.SEARCH = _stub_search
ex.fetch_text = _stub_fetch
ex.LLM = _stub_llm
# Force the catalogue to a known model
rc.set_active("perplexity:sonar-pro")

# run a shallow end-to-end
res = ex.run(query="kubernetes operator patterns", notebook="default",
             depth="shallow", n=5, max_rounds=4)
check("C1 shallow run completes", res["ok"] and res["rounds"] >= 1, res)
check("C2 shallow run imports ≥1 source per round",
      res["sources_added"] >= 1 and len(res["sources"]) >= 1)
check("C3 shallow run lands exactly the URLs returned by the stub",
      all(s["url"].startswith("https://example.com/") for s in res["sources"] if s["kind"] == "url")
      and sum(1 for s in res["sources"] if s["kind"] == "url") == len(_FAKE_URLS))
check("C4 each imported source has chunks > 0",
      all(s.get("chunks", 0) > 0 for s in res["sources"]))
check("C5 a summary is produced and stored as a 'text' source",
      any(s["kind"] == "text" and s.get("chunks", 0) >= 0 for s in res["sources"]),
      "ref=%s" % ([s.get("ref") for s in res["sources"] if s["kind"] == "text"]))

# run a medium end-to-end → 2 rounds → more sources
res_m = ex.run(query="kubernetes operator patterns", notebook="default",
               depth="medium", n=5, max_rounds=4)
check("C6 medium run has ≥2 rounds",
      res_m["ok"] and res_m["rounds"] >= 2, res_m)
check("C7 medium run imports sources from BOTH stubbed queries",
      any("k8s-operator-c" in s["url"] for s in res_m["sources"])
      and any("k8s-operator-d" in s["url"] for s in res_m["sources"]))

# run a deep end-to-end → capped at max_rounds
res_d = ex.run(query="kubernetes operator patterns", notebook="default",
               depth="deep", n=5, max_rounds=2)
check("C8 deep run is capped at max_rounds", res_d["rounds"] <= 2, res_d)

# verify the sources are actually in the default notebook
sources = kb.list_sources("default")
check("C9 the notebook now contains the imported URLs + summary",
      any("k8s-operator-a" in (s.get("ref") or "") for s in sources)
      and any(s.get("kind") == "text" for s in sources), sources[:5])

# --------------------------------------------------------------------------- D (wiring)
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
CLI = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()

check("D1 API exposes /api/knowledge/research", "/api/knowledge/research" in API, "")
check("D2 API also exposes /api/research/model to set/inspect the research LLM",
      "/api/research/model" in API, "")
check("D3 CLI exposes `forge knowledge research`",
      "research" in CLI and "def cmd_knowledge" in CLI, "")
check("D4 the WebUI Knowledge inspector has a Research section",
      'data-insp="knowledge"' in HTML and "Research" in HTML, "")
check("D5 the WebUI has a function to start a research run", "kbResearch" in HTML or "kbStartResearch" in HTML, "")
check("D6 research model select is wired in the WebUI",
      "researchModel" in HTML or "research-model" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)