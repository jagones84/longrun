#!/usr/bin/env python3
"""Run the build watcher behavior test in the JavaScript runtime."""
import os
import shutil
import subprocess
import sys

node = shutil.which("node")
if not node:
    print("SKIP build watcher behavior: node is not installed")
    sys.exit(0)

test = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1160_build_watcher.js")
sys.exit(subprocess.call([node, test]))
