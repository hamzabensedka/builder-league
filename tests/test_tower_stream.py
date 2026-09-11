"""TowerCore EventStream: append-only spine, seq enforcement, fan-out, tail."""

import pytest

from core.towercore.domain.events import make_event
from core.towercore.domain.stream import EventStream


def ev(agent="a1", run="r1", seq=1, kind="step_started", payload=None, ts="t"):
    return make_event(agent_id=agent, run_id=run, seq=seq, ts=ts, kind=kind,
                      payload=payload or {})


class TestAppend:
    def test_append_and_read_back(self):
        s = EventStream()
        s.append(ev(seq=1))
        s.append(ev(seq=2, kind="action_executed"))
        assert len(s.all()) == 2

    def test_per_agent_seq_must_be_contiguous(self):
        s = EventStream()
        s.append(ev(seq=1))
        with pytest.raises(ValueError, match="seq"):
            s.append(ev(seq=3))  # gap → fail-closed

    def test_seq_tracks_agents_independently(self):
        s = EventStream()
        s.append(ev(agent="a1", seq=1))
        s.append(ev(agent="a2", seq=1))  # fine: different agent
        s.append(ev(agent="a1", seq=2))
        assert [e.seq for e in s.for_agent("a1")] == [1, 2]

    def test_duplicate_seq_rejected(self):
        s = EventStream()
        s.append(ev(seq=1))
        with pytest.raises(ValueError, match="seq"):
            s.append(ev(seq=1))

    def test_next_seq_helper(self):
        s = EventStream()
        assert s.next_seq("a1") == 1
        s.append(ev(seq=1))
        assert s.next_seq("a1") == 2


class TestQueries:
    def test_for_agent_filters(self):
        s = EventStream()
        s.append(ev(agent="a1", seq=1))
        s.append(ev(agent="a2", seq=1))
        s.append(ev(agent="a1", seq=2))
        assert len(s.for_agent("a1")) == 2
        assert len(s.for_agent("a2")) == 1
        assert s.for_agent("nobody") == []

    def test_tail_returns_last_n(self):
        s = EventStream()
        for i in range(1, 8):
            s.append(ev(seq=i))
        tail = s.tail("a1", 3)
        assert [e.seq for e in tail] == [5, 6, 7]

    def test_tail_larger_than_log_returns_all(self):
        s = EventStream()
        s.append(ev(seq=1))
        assert len(s.tail("a1", 50)) == 1

    def test_export_returns_canonical_dicts_in_order(self):
        s = EventStream()
        s.append(ev(agent="a2", seq=1, kind="step_started"))
        s.append(ev(agent="a1", seq=1, kind="action_denied"))
        out = s.export()
        assert [d["agent_id"] for d in out] == ["a2", "a1"]
        assert out[1]["kind"] == "action_denied"


class TestFanOut:
    def test_subscriber_receives_new_events(self):
        s = EventStream()
        received = []
        s.subscribe(received.append)
        s.append(ev(seq=1))
        s.append(ev(seq=2))
        assert [e.seq for e in received] == [1, 2]

    def test_subscriber_does_not_replay_history(self):
        s = EventStream()
        s.append(ev(seq=1))
        received = []
        s.subscribe(received.append)
        assert received == []

    def test_multiple_subscribers(self):
        s = EventStream()
        a, b = [], []
        s.subscribe(a.append)
        s.subscribe(b.append)
        s.append(ev(seq=1))
        assert len(a) == len(b) == 1

    def test_failing_subscriber_does_not_break_stream(self):
        s = EventStream()
        s.subscribe(lambda e: 1 / 0)
        good = []
        s.subscribe(good.append)
        s.append(ev(seq=1))  # must not raise
        assert len(good) == 1

    def test_unsubscribe(self):
        s = EventStream()
        received = []
        unsub = s.subscribe(received.append)
        s.append(ev(seq=1))
        unsub()
        s.append(ev(seq=2))
        assert len(received) == 1


class TestAppendOnly:
    def test_no_mutation_surface(self):
        # append-only by design: no update/delete methods exist
        assert not hasattr(EventStream, "update")
        assert not hasattr(EventStream, "delete")
        assert not hasattr(EventStream, "remove")
