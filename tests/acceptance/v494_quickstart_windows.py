#!/usr/bin/env python3
"""v494 — README quickstarts give accurate, ordered setup steps.

Guards the first-run path users follow: one PowerShell launcher command, automatic
required-dependency bootstrap, browser launch, provider examples, no private
machine addresses, and optional MCP/skill setup instructions.
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


start = README.split("## Quick start: Windows", 1)[1].split("## What Longrun does", 1)[0]
linux = README.split("## Quick start: Linux", 1)[1].split("## Model setup", 1)[0]
install = README.split("## Model setup", 1)[1].split("## Secrets and local settings", 1)[0]
guide = start + linux + install + README
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
check("A3 DGX quick start confirms ARM64 and installs distro PyYAML",
      "uname -m" in linux and "aarch64" in linux and "python3-yaml" in linux)
common_setup_links = (
    "[Model setup](#model-setup)",
    "[Secrets and local settings](#secrets-and-local-settings)",
    "[MCP servers and skills](#optional-mcp-servers-and-skills)",
    "[remote access](#remote-access)",
    "[document extraction](#optional-document-extraction)",
    "[sandbox](#sandbox)",
)
linux_setup_links = common_setup_links + ("[Linux service](#optional-linux-service)",)
setup_headings = (
    "## Model setup",
    "### Secrets and local settings",
    "### Optional: MCP servers and skills",
    "### Remote access",
    "### Optional Linux service",
    "### Optional document extraction",
    "### Sandbox",
)
check("A4 Windows quick start links to full setup and optional instructions",
      all(link in start for link in common_setup_links)
      and all(heading in README for heading in setup_headings))
check("A5 Linux quick start links to full setup and optional instructions",
      all(link in linux for link in linux_setup_links)
      and all(heading in README for heading in setup_headings))

check("B1 OpenRouter account and API-key destination are linked",
      "https://openrouter.ai/" in README
      and "https://openrouter.ai/settings/keys" in README
      and "OPENROUTER_API_KEY" in README
      and "Settings" in README and "Keys" in README)
check("B2 README distinguishes server token from provider API key",
      "first-run panel" in guide.lower()
      and "OPENROUTER_API_KEY" in guide
      and "LONGRUN_TOKEN" in guide
      and "protects Longrun" in guide
      and "provider keys authorize" in guide)
check("B3 README names the physical ignored key file",
      'os.path.join(REPO, ".env")' in KEYS and ".env" in read(".gitignore")
      and "<repository>/.env" in guide)

check("C1 README shows a selectable OpenRouter model without claiming a default",
      "openrouter:openrouter/auto" in PROVIDERS
      and "openrouter:openai/gpt-4o-mini" in guide
      and "openrouter:openrouter/auto" not in README
      and "pattern: qwen" in ROUTING
      and "pattern: qwen" not in README)
check("C2 README omits machine-specific role and compaction defaults",
      "openrouter:meta/muse-spark-1.3-contributor" in ROUTING
      and "openrouter:z-ai/glm-5.3-flash" in ROUTING
      and "openrouter:deepseek/deepseek-v4-flash-0731" in ROUTING
      and "trigger_pct: 70" in COMPACTION
      and all(ref not in README for ref in (
          "openrouter:meta/muse-spark-1.3-contributor",
          "openrouter:z-ai/glm-5.3-flash",
          "openrouter:deepseek/deepseek-v4-flash-0731",
          "70% context, target 30%")))

check("D1 MCP is optional and has a UI catalog setup path",
      "Settings" in guide and "MCP" in guide and "npx" in guide
      and "GITHUB_TOKEN" in guide and "mcp_clients.local.json" in guide
      and "MCP JSON" in guide and "Streamable HTTP" in guide
      and "absolute allowed directory" in guide and "`${VARIABLE_NAME}`" in guide
      and "Click **reload**" in guide)
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
