#!/usr/bin/env python3
"""Harness² adapter package — the evidence half of recursive harness refinement.

The paper (arXiv:2610.14224) refines a harness on the task in front of it with a
contrastive Propose–Probe–Compose step that needs no answer key. What makes that
possible is not the model: it is a *record* of how the base run behaved and a
mechanical *contrast* between two records.

This package carries only that evidence machinery. It never writes harness code:
every adopted change goes through `util.improve.propose` and stays a proposal for
the operator (see `util/improve.py:21-27`).
"""
