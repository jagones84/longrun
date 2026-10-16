"""Longrun integrations: bridges to external agent/runtime products.

Nothing here is imported by the Longrun server itself. The package exists so a
bridge can be developed and tested without a provider, a network, or the WebUI.

``paperclip_adapter`` is the stdlib-only REST/SSE bridge that lets the external
Paperclip adapter drive exactly one Longrun agent run.
"""
