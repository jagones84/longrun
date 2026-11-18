#!/usr/bin/env python3
"""Run the shared-feed turn channel test in the JavaScript runtime."""
import os
import shutil
import subprocess
import sys

node = shutil.which("node")
if not node:
    print("SKIP turn channels behavior: node is not installed")
    sys.exit(0)

test = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1165_turn_channels.js")
sys.exit(subprocess.call([node, test]))
