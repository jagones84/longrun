"""OpenTelemetry tracing for Longrun runs.

When the `opentelemetry-sdk` package is installed, RunTrace spans are recorded
through the real OTel SDK (genuine trace_id / span_id / parent hierarchy and
nanosecond timestamps) and exported synchronously into the runs table, so
`GET /api/runs/<id>/trace` serves true OTel spans. Without the SDK the harness
falls back to lightweight local spans with the same `name`/`ts` shape.

Stdlib only besides the optional OTel SDK. Local-first: spans are exported to
the local SQLite store, not to any cloud endpoint.
"""

import threading

_lock = threading.Lock()
_spans_by_run = {}
_provider_ready = False


def otel_available():
    try:
        import opentelemetry.sdk  # noqa: F401
        return True
    except ImportError:
        return False


class _RunSpanExporter:
    """Synchronous SpanExporter that keeps ended spans in memory, grouped by
    run_id (attached as the `longrun.run_id` span attribute)."""

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult

        for s in spans:
            attrs = dict(s.attributes or {})
            run_id = attrs.pop("longrun.run_id", None)
            if not run_id:
                continue
            ctx = s.get_span_context()
            rec = {
                "name": s.name,
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
                "parent_span_id": (format(s.parent.span_id, "016x") if s.parent else None),
                "start_ns": s.start_time,
                "end_ns": s.end_time,
                "ts": round((s.start_time or 0) / 1e9, 3),
                "attributes": {k: _attr_value(v) for k, v in attrs.items()},
                "status": str(s.status.status_code.name).lower(),
            }
            with _lock:
                if len(_spans_by_run) > 256 and run_id not in _spans_by_run:
                    _spans_by_run.pop(next(iter(_spans_by_run)), None)
                _spans_by_run.setdefault(run_id, []).append(rec)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


def _attr_value(v):
    if isinstance(v, (list, tuple)):
        return [str(x) if not isinstance(x, (int, float, bool, str)) else x for x in v]
    return v if isinstance(v, (int, float, bool, str)) else str(v)


def init_provider():
    """Install the TracerProvider once. Returns True when OTel is active."""
    global _provider_ready
    if _provider_ready or not otel_available():
        return _provider_ready
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({
        "service.name": "longrun",
        "service.version": "0.4.0",
    }))
    provider.add_span_processor(SimpleSpanProcessor(_RunSpanExporter()))
    trace.set_tracer_provider(provider)
    _provider_ready = True
    return True


def get_tracer():
    from opentelemetry import trace
    return trace.get_tracer("longrun")


def take_spans(run_id):
    """Detach and return the OTel spans exported for this run (in order)."""
    with _lock:
        return _spans_by_run.pop(run_id, [])

