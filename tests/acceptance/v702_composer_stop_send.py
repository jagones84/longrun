#!/usr/bin/env python3
"""v702: while a turn runs, a typed prompt SENDS (queue/steer); Stop stays reachable.

The operator asked for exactly this: during a steer/queue turn the red stop button
must become send, so the prompt in the chat bar can be queued/steered — without
losing the panic Stop. EV-42 (operator, 2026-10-30): the separate LEFT stop chip
looked like a second button ("si genera il bottone anche a sinistra … perché
mai???"), so it is gone: the toolbar keeps ONE button, and Esc (caret in the
composer) stops the running turn when a draft is typed.

The display function is executed for real (Node), not grepped, and the routing
function is executed with stubs.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v702-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    UI = _f.read()

START = "function composerBusy() {"
END = "/* JAG-218:"
FUNCS = START + UI.split(START, 1)[1].split(END, 1)[0]


def run_js(script):
    node = shutil.which("node")
    if node is None:
        installed = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
        node = installed[-1] if installed else "node"
    result = subprocess.run([node], input=script, text=True, capture_output=True, timeout=10)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


HARNESS = """
let sessionId = "s1";
const runningSessions = {s1: BUSY};
const _attachmentPending = () => false;
const _q = () => [];
const localStorage = {getItem: () => QMODE};
let stopped = 0, sent = 0;
function stopRun() { stopped += 1; }
function send() { sent += 1; }
const nodes = {
  inp: {value: DRAFT},
  sendBtn: {classList: {_c: new Set(),
                        toggle(k, on) { on ? this._c.add(k) : this._c.delete(k); },
                        has(k) { return this._c.has(k); }},
            setAttribute(k, v) { this[k] = v; }},
};
const $ = id => nodes[id];
FUNCS
refreshSendBtn();
sendOrStop();
const b = nodes.sendBtn;
console.log(JSON.stringify({text: b.textContent, stop: b.classList.has("stop"),
                            title: b.title, label: b["aria-label"],
                            stopped: stopped, sent: sent}));
"""


def state(busy, draft, qmode="queue"):
    script = (HARNESS.replace("BUSY", "true" if busy else "false")
                     .replace("QMODE", json.dumps(qmode))
                     .replace("DRAFT", json.dumps(draft))
                     .replace("FUNCS", FUNCS))
    return run_js(script)


class ComposerStopSend(unittest.TestCase):
    def test_idle_sends(self):
        got = state(False, "", "queue")
        self.assertEqual(got["text"], "↑")
        self.assertFalse(got["stop"])
        self.assertEqual((got["stopped"], got["sent"]), (0, 1))

    def test_busy_with_an_empty_box_is_the_red_stop(self):
        got = state(True, "   ", "queue")
        self.assertEqual(got["text"], "■")
        self.assertTrue(got["stop"])
        self.assertEqual(got["label"], "stop")
        self.assertEqual((got["stopped"], got["sent"]), (1, 0))

    def test_busy_with_a_draft_sends_in_queue_mode(self):
        got = state(True, "add the missing test", "queue")
        self.assertEqual(got["text"], "↑")
        self.assertFalse(got["stop"])
        self.assertEqual(got["label"], "send")
        self.assertIn("queue this prompt", got["title"])
        self.assertIn("Esc stops the turn", got["title"])   # EV-42: one button only
        self.assertEqual((got["stopped"], got["sent"]), (0, 1))

    def test_busy_with_a_draft_sends_in_steer_mode(self):
        got = state(True, "steer me", "steer")
        self.assertEqual(got["text"], "↑")
        self.assertIn("steer this prompt", got["title"])
        self.assertEqual((got["stopped"], got["sent"]), (0, 1))

    def test_the_toolbar_has_ONE_button_and_esc_is_the_stop(self):
        # EV-42: no second stop control on the left; Esc in the composer stops.
        self.assertNotIn('id="stopChip"', UI)
        self.assertIn('e.key === "Escape" && composerBusy()', UI)
        self.assertIn("function composerDraft()", UI)
        self.assertIn("skillsAutocomplete(); _renderCmdChips(); refreshSendBtn();", UI)


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ComposerStopSend))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
