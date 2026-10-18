#!/usr/bin/env python3
"""v494 — a fresh Windows clone can launch and configure itself from the UI.

Guards the first-run path users follow: one PowerShell launcher command, automatic
required-dependency bootstrap, browser launch, an OpenRouter key link + UI save
path, accurate shipped model defaults, and optional MCP/skill setup instructions.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


README = read("README.md")
LAUNCHER = read("run.ps1")
PROVIDERS = read("config", "providers.yaml")
ROUTING = read("config", "routing.yaml")
COMPACTION = read("config", "compaction.yaml")
KEYS = read("src", "longrun", "model", "keys.py")
SERVICE = read("deploy", "longrun.service")
SKILLS = read("src", "longrun", "memory", "skills.py")
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.pop("LONGRUN_SKILLS_LOCAL_DIR", None)
from longrun.memory import skills as skill_store  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


start = README.split("## Quick start", 1)[-1].split("## Why Longrun", 1)[0]
install = README.split("## Install & run", 1)[-1].split("## API & integration", 1)[0]
guide = start + install
check("A1 Windows quick start uses the policy-bypass launcher and one URL",
      "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\run.ps1" in start
      and "http://127.0.0.1:8790/" in start
      and "run.sh" not in start)
check("A2 Windows launcher installs the required dependency and opens the UI",
      "pip install --user PyYAML" in LAUNCHER
      and "-m pip show PyYAML" in LAUNCHER
      and "--version" in LAUNCHER
      and " -c " not in LAUNCHER
      and "Start-Process" in LAUNCHER)

check("B1 OpenRouter account and API-key destination are linked",
      "https://openrouter.ai/" in start
      and "https://openrouter.ai/settings/keys" in start
      and "OPENROUTER_API_KEY" in start
      and "Settings" in start and "Keys" in start)
check("B2 README distinguishes server token from provider API key",
      "First-run security setup" in guide
      and "OPENROUTER_API_KEY" in guide
      and "LONGRUN_TOKEN" in guide
      and "different" in guide.lower())
check("B3 README names the physical ignored key file",
      'os.path.join(REPO, ".env")' in KEYS and ".env" in read(".gitignore")
      and "repo-root" in guide.lower()
      and r"C:\Users\you\longrun\.env" in guide)

check("C1 docs match the shipped cloud default and optional local chat pattern",
      "openrouter:openrouter/auto" in PROVIDERS
      and "openrouter:openrouter/auto" in guide
      and "pattern: qwen" in ROUTING
      and "qwen" in guide.lower())
check("C2 docs match shipped compaction and agent-role model pins",
      "openrouter:meta/muse-spark-1.3-contributor" in ROUTING
      and "openrouter:z-ai/glm-5.3-flash" in ROUTING
      and "openrouter:deepseek/deepseek-v4-flash-0731" in ROUTING
      and "trigger_pct: 70" in COMPACTION
      and all(ref in guide for ref in (
          "openrouter:meta/muse-spark-1.3-contributor",
          "openrouter:z-ai/glm-5.3-flash",
          "openrouter:deepseek/deepseek-v4-flash-0731")))

check("D1 MCP is optional and has a UI catalog setup path",
      "Settings" in guide and "MCP" in guide and "npx" in guide
      and "GITHUB_TOKEN" in guide and "mcp_clients.local.json" in guide)
check("D2 skills are optional, installed from ZIP, and stored in skills/local",
      "Settings" in guide and "Skills" in guide and ".zip" in guide
      and "skills/local" in guide
      and os.path.normcase(skill_store._local_dir())
      == os.path.normcase(os.path.join(REPO, "skills", "local")))
check("E1 systemd and interactive setup use the same repo .env token source",
      "EnvironmentFile=-%h/Repositories/longrun/.env" in SERVICE
      and "EnvironmentFile=-%h/.config/longrun/env" not in SERVICE)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
