#!/usr/bin/env python3
"""v496 — custom OpenAI-compatible local model providers are selectable."""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v496-")
os.environ["LONGRUN_PROVIDERS_LOCAL"] = os.path.join(TMP, "providers.local.yaml")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import providers  # noqa: E402

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as source:
    UI = source.read()
with open(os.path.join(REPO, "README.md"), encoding="utf-8") as source:
    README = source.read()

results = []


def check(name, passed, detail=""):
    results.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


for spec, ref, expected_url in (
    (
        {
            "id": "ollama",
            "kind": "openai",
            "base_url": "http://127.0.0.1:11434/v1",
            "local": True,
            "models": [{"id": "llama3.2:3b"}],
        },
        "ollama:llama3.2:3b",
        "http://127.0.0.1:11434/v1/chat/completions",
    ),
    (
        {
            "id": "lmstudio",
            "kind": "openai",
            "base_url": "http://127.0.0.1:1234/v1",
            "local": True,
            "models": [{"id": "qwen3-8b"}],
        },
        "lmstudio:qwen3-8b",
        "http://127.0.0.1:1234/v1/chat/completions",
    ),
):
    saved = providers.upsert_provider(spec)
    resolved = providers.resolve(ref)
    endpoint = providers.endpoint(ref)
    check(spec["id"] + " provider can be added to the local overlay",
          saved.get("ok") is True and os.path.isfile(providers.LOCAL_CONFIG))
    check(spec["id"] + " namespaced model resolves to OpenAI chat completions",
          resolved is not None and resolved[1] == ref.split(":", 1)[1]
          and endpoint is not None and endpoint[0] == expected_url)
    check(spec["id"] + " local provider is available without a provider key",
          resolved is not None and providers.available(resolved[0])
          and "Authorization" not in providers.headers(resolved[0]))

save_start = UI.index("async function saveProvider()")
save_end = UI.index("/* ---- keys", save_start)
save_provider_ui = UI[save_start:save_end]
check("saving a provider refreshes the chat model picker",
      bool(re.search(r"if\s*\(!r\.error\)\s*\{[\s\S]*?await loadProviders\(\);[\s\S]*?await loadModels\(\);",
                     save_provider_ui, re.DOTALL)))
check("unauthorized provider saves offer a direct Keys recovery action",
      'id="provAuthRecovery"' in UI
      and 'data-call="openSettings" data-args=\'["keys"]\'' in UI
      and "Provider was not saved" in UI)
check("provider form draft survives the token-save page reload",
      "_saveProviderDraft()" in save_provider_ui
      and "sessionStorage.setItem" in UI
      and "function _restoreProviderDraft()" in UI
      and "sessionStorage.removeItem" in save_provider_ui
      and "_restoreProviderDraft();" in UI)
restore_start = UI.index("function _restoreProviderDraft()")
restore_end = UI.index("/* ---- keys", restore_start)
restore_provider_ui = UI[restore_start:restore_end]
check("restored draft does not claim the corrected token is still rejected",
      'id="provAuthMessage"' in UI
      and '$("provAuthMessage").textContent =' in restore_provider_ui
      and "Unsaved provider draft restored" in restore_provider_ui)
check("README documents Ollama, llama.cpp, and LM Studio setup",
      all(term in README for term in (
          "Ollama", "LM Studio", "Settings → Models", "11434/v1",
          "llama.cpp", "llamacpp-local", "8080/v1", "/v1/models",
          "1234/v1", "local (no key)")))

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
