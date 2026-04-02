from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from alarm_brain.engine import AlarmEngine
from alarm_brain.storage import load_state, save_state


def _new_engine():
    state = {"version": 1, "next_id": 1, "alarms": [], "timers": []}
    return AlarmEngine(state=state, timezone=ZoneInfo("UTC"), default_snooze_minutes=10)


def test_oneoff_triggers_and_dismiss_disables():
    engine = _new_engine()
    now = datetime(2026, 3, 27, 7, 0, 0, tzinfo=ZoneInfo("UTC"))
    engine.add_oneoff("2026-03-27T07:00:00+00:00", label="Wake", now=now)

    events, changed = engine.tick(now=now)
    assert changed
    assert len(events["alarms_triggered"]) == 1

    dismissed = engine.dismiss(now=now)
    assert dismissed["enabled"] is False


def test_recurring_dismiss_keeps_enabled():
    engine = _new_engine()
    now = datetime(2026, 3, 27, 7, 0, 0, tzinfo=ZoneInfo("UTC"))  # Friday
    alarm = engine.add_recurring("07:00", [4], label="Weekly", now=now)

    events, changed = engine.tick(now=now)
    assert changed
    assert len(events["alarms_triggered"]) == 1

    dismissed = engine.dismiss(alarm_id=alarm["id"], now=now)
    assert dismissed["enabled"] is True

    next_week = now + timedelta(days=7)
    events2, changed2 = engine.tick(now=next_week)
    assert changed2
    assert len(events2["alarms_triggered"]) == 1


def test_storage_roundtrip(tmp_path: Path):
    path = tmp_path / "alarm_state.json"
    state = {"version": 1, "next_id": 3, "alarms": [{"id": 1}], "timers": [{"id": 2}]}
    save_state(path, state)

    loaded = load_state(path)
    assert loaded["next_id"] == 3
    assert loaded["alarms"][0]["id"] == 1
    assert loaded["timers"][0]["id"] == 2
