from types import SimpleNamespace

from app.infrastructure.observability.langfuse_tracing import LangfuseTracer
from app.infrastructure.observability.tracing import CompositeTracer


class _FakeSpan:
    def __init__(self) -> None:
        self.ended_with = None

    def end(self, **kwargs) -> None:
        self.ended_with = kwargs


class _FakeTrace:
    def __init__(self) -> None:
        self.spans = []

    def span(self, **kwargs):
        self.spans.append(kwargs)
        return _FakeSpan()


class _FakeClient:
    def __init__(self) -> None:
        self.created_trace = _FakeTrace()

    def trace(self, **kwargs):
        return self.created_trace


class _SpanTracer:
    def __init__(self) -> None:
        self.started = []
        self.ended = []

    def span(self, handle, name, **kwargs):
        payload = {"handle": handle, "name": name, **kwargs}
        self.started.append(payload)
        return payload

    def end_span(self, span, **kwargs):
        self.ended.append((span, kwargs))


def test_langfuse_tracer_span_and_end_span_are_best_effort():
    tracer = LangfuseTracer(_FakeClient())
    handle = tracer.start("question", SimpleNamespace(id="u1", role="hr"), "s1")

    span = tracer.span(handle, "tool.rag_search", input={"query": "q"})

    assert span is not None
    tracer.end_span(span, output={"ok": True}, level="ERROR")
    assert span.ended_with is not None
    assert span.ended_with["output"] == {"ok": True}
    assert span.ended_with["level"] == "ERROR"


def test_composite_tracer_span_skips_backends_without_span_support():
    supported = _SpanTracer()
    unsupported = object()
    composite = CompositeTracer([supported, unsupported])

    span_handle = composite.span(
        [(supported, "supported-handle"), (unsupported, "unsupported-handle")],
        "tool.hr_query",
        input={"intent": "leave_balance"},
    )

    assert span_handle == [
        (
            supported,
            {
                "handle": "supported-handle",
                "name": "tool.hr_query",
                "input": {"intent": "leave_balance"},
            },
        )
    ]

    composite.end_span(span_handle, output="done")
    assert supported.ended == [
        (
            {
                "handle": "supported-handle",
                "name": "tool.hr_query",
                "input": {"intent": "leave_balance"},
            },
            {"output": "done"},
        )
    ]
