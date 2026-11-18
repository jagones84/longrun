#!/usr/bin/env python3
"""Run the sessions refresh coordinator behavior test."""
import os
import shutil
import subprocess
import sys

node = shutil.which("node")
if not node:
    print("SKIP sessions refresh coordinator: node is not installed")
    sys.exit(0)

test = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1164_sessions_refresh.js")
sys.exit(subprocess.call([node, test]))
