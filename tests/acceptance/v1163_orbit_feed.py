#!/usr/bin/env python3
"""Run the embedded Orbit feed bridge behavior test."""
import os
import shutil
import subprocess
import sys

node = shutil.which("node")
if not node:
    print("SKIP Orbit feed bridge: node is not installed")
    sys.exit(0)

test = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1163_orbit_feed.js")
sys.exit(subprocess.call([node, test]))
