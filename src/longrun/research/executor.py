"""RESEARCH executor (JAG-403b) — runs the plan and imports the results.

Wraps :mod:`longrun.research.research` and exposes the indirections tests (and
alternative live implementations) can override: ``SEARCH``, ``fetch_text``,
``LLM``.
"""
from longrun.research.research import (  # noqa: F401
    run, status, make_plan,
    SEARCH, fetch_text, LLM,
)