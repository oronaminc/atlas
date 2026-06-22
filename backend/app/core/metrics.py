"""Zero-dependency Prometheus metrics registry (text exposition 0.0.4).

Air-gap: no prometheus_client dep. One registry per PROCESS — the API and
each worker pod expose their own /metrics, scraped independently. Counters/
gauges/histograms are process-local; cross-pod DB-derived gauges are computed
at scrape time on the API (see app/api/v1/metrics.py).

Label cardinality is the caller's responsibility: hot-path series use only
fixed low-cardinality labels (provider/channel/reason/outcome). Per-service
series are emitted ONLY on soft-cap breach (normally zero series).
"""

import math
import threading
from collections.abc import Iterable

_NAME_DOC: dict[str, str] = {}


def _fmt_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_escape(str(v))}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class _Metric:
    def __init__(self, name: str, doc: str, labelnames: tuple[str, ...] = ()):
        self.name = name
        self.doc = doc
        self.labelnames = labelnames
        self._lock = threading.Lock()
        _NAME_DOC[name] = doc

    def _key(self, labels: dict[str, str]) -> tuple:
        return tuple(labels.get(n, "") for n in self.labelnames)


class Counter(_Metric):
    _type = "counter"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def samples(self) -> Iterable[tuple[dict, float]]:
        with self._lock:
            items = list(self._values.items())
        for key, val in items:
            yield dict(zip(self.labelnames, key, strict=False)), val


class Gauge(_Metric):
    _type = "gauge"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._values: dict[tuple, float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = value

    def clear(self) -> None:
        """Drop all series — used for breach-only gauges so resolved
        breaches stop being exported (cardinality stays bounded)."""
        with self._lock:
            self._values.clear()

    def samples(self) -> Iterable[tuple[dict, float]]:
        with self._lock:
            items = list(self._values.items())
        for key, val in items:
            yield dict(zip(self.labelnames, key, strict=False)), val


# fixed latency buckets (seconds) — ingest p95 ~20ms, send ~50ms RTT
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Histogram(_Metric):
    _type = "histogram"

    def __init__(self, *a, buckets: tuple[float, ...] = DEFAULT_BUCKETS, **k):
        super().__init__(*a, **k)
        self._buckets = buckets
        self._counts: dict[tuple, list[int]] = {}
        self._sum: dict[tuple, float] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            counts = self._counts.get(key)
            if counts is None:
                counts = [0] * (len(self._buckets) + 1)  # +Inf
                self._counts[key] = counts
                self._sum[key] = 0.0
            for i, edge in enumerate(self._buckets):
                if value <= edge:
                    counts[i] += 1
            counts[-1] += 1  # +Inf always
            self._sum[key] += value

    def render_lines(self) -> list[str]:
        lines = []
        with self._lock:
            items = list(self._counts.items())
            sums = dict(self._sum)
        for key, counts in items:
            base = dict(zip(self.labelnames, key, strict=False))
            for i, edge in enumerate(self._buckets):
                le = repr(edge) if not math.isinf(edge) else "+Inf"
                lines.append(f"{self.name}_bucket{_fmt_labels({**base, 'le': le})} {counts[i]}")
            total = counts[-1]
            lines.append(f"{self.name}_bucket{_fmt_labels({**base, 'le': '+Inf'})} {total}")
            lines.append(f"{self.name}_sum{_fmt_labels(base)} {sums[key]}")
            lines.append(f"{self.name}_count{_fmt_labels(base)} {total}")
        return lines


class Registry:
    def __init__(self) -> None:
        self._metrics: list[_Metric] = []

    def register(self, metric: _Metric) -> _Metric:
        self._metrics.append(metric)
        return metric

    def counter(self, name, doc, labelnames=()) -> Counter:
        return self.register(Counter(name, doc, labelnames))

    def gauge(self, name, doc, labelnames=()) -> Gauge:
        return self.register(Gauge(name, doc, labelnames))

    def histogram(self, name, doc, labelnames=(), buckets=DEFAULT_BUCKETS) -> Histogram:
        return self.register(Histogram(name, doc, labelnames, buckets=buckets))

    def render(self) -> str:
        out: list[str] = []
        for m in self._metrics:
            out.append(f"# HELP {m.name} {m.doc}")
            out.append(f"# TYPE {m.name} {m._type}")
            if isinstance(m, Histogram):
                out.extend(m.render_lines())
            else:
                for labels, val in m.samples():
                    out.append(f"{m.name}{_fmt_labels(labels)} {_render_value(val)}")
        return "\n".join(out) + "\n"


def _render_value(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return repr(v)


CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# the single process-wide registry
REGISTRY = Registry()
