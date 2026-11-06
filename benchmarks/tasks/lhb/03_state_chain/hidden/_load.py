#!/usr/bin/env python3
"""Shared loader for the chain task's hidden tests."""
import importlib.util
import os
from pathlib import Path


def load():
    """Import out/pipeline.py from the arm's workspace."""
    path = Path(os.environ["LHB_WS"]) / "out" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("lhb_pipeline", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
