"""Stage-1 dedup: fingerprint window via injectable store (Redis in prod,
in-memory here)."""

from app.services.correlation.dedup import InMemoryDedupStore


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def test_first_occurrence_is_not_duplicate():
    store = InMemoryDedupStore(clock=FakeClock())
    assert await store.seen_within("fp1", window_seconds=300) is False


async def test_repeat_within_window_is_duplicate():
    store = InMemoryDedupStore(clock=FakeClock())
    await store.seen_within("fp1", window_seconds=300)
    assert await store.seen_within("fp1", window_seconds=300) is True


async def test_repeat_after_window_is_fresh():
    clock = FakeClock()
    store = InMemoryDedupStore(clock=clock)
    await store.seen_within("fp1", window_seconds=300)
    clock.t += 301
    assert await store.seen_within("fp1", window_seconds=300) is False


async def test_fingerprints_are_independent():
    store = InMemoryDedupStore(clock=FakeClock())
    await store.seen_within("fp1", window_seconds=300)
    assert await store.seen_within("fp2", window_seconds=300) is False
