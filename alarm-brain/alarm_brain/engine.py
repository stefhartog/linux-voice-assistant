"""Core scheduling engine for alarms and timers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class AlarmEngine:
    def __init__(
        self,
        state: Dict[str, Any],
        timezone: ZoneInfo,
        default_snooze_minutes: int = 10,
    ) -> None:
        self.state = state
        self.timezone = timezone
        self.default_snooze_minutes = default_snooze_minutes
        self.ringing_alarm_ids: set[int] = set()

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def _next_id(self) -> int:
        next_id = int(self.state.get("next_id", 1))
        self.state["next_id"] = next_id + 1
        return next_id

    def _parse_datetime(self, value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.timezone)
        return dt.astimezone(self.timezone)

    def _parse_hhmm(self, hhmm: str) -> Tuple[int, int]:
        pieces = hhmm.split(":")
        if len(pieces) != 2:
            raise ValueError("time must be HH:MM")
        hour, minute = int(pieces[0]), int(pieces[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("time must be HH:MM")
        return hour, minute

    def _get_alarm(self, alarm_id: int) -> Dict[str, Any]:
        for alarm in self.state["alarms"]:
            if int(alarm["id"]) == alarm_id:
                return alarm
        raise ValueError(f"alarm id {alarm_id} not found")

    def _get_timer(self, timer_id: int) -> Dict[str, Any]:
        for timer in self.state["timers"]:
            if int(timer["id"]) == timer_id:
                return timer
        raise ValueError(f"timer id {timer_id} not found")

    def add_oneoff(self, when: str, label: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.now()
        trigger_at = self._parse_datetime(when)
        alarm = {
            "id": self._next_id(),
            "kind": "oneoff",
            "label": label,
            "enabled": True,
            "oneoff_time": _iso(trigger_at),
            "recurring_time": None,
            "weekdays": [],
            "snooze_until": None,
            "last_triggered_at": None,
            "last_triggered_date": None,
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        self.state["alarms"].append(alarm)
        return alarm

    def add_recurring(
        self,
        hhmm: str,
        weekdays: List[int],
        label: str = "",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or self.now()
        self._parse_hhmm(hhmm)

        clean_weekdays = sorted({int(day) for day in weekdays})
        if not clean_weekdays:
            raise ValueError("weekdays cannot be empty")
        if any(day < 0 or day > 6 for day in clean_weekdays):
            raise ValueError("weekdays must be 0..6")

        alarm = {
            "id": self._next_id(),
            "kind": "recurring",
            "label": label,
            "enabled": True,
            "oneoff_time": None,
            "recurring_time": hhmm,
            "weekdays": clean_weekdays,
            "snooze_until": None,
            "last_triggered_at": None,
            "last_triggered_date": None,
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        self.state["alarms"].append(alarm)
        return alarm

    def remove_alarm(self, alarm_id: int) -> bool:
        before = len(self.state["alarms"])
        self.state["alarms"] = [a for a in self.state["alarms"] if int(a["id"]) != alarm_id]
        self.ringing_alarm_ids.discard(alarm_id)
        return len(self.state["alarms"]) != before

    def update_alarm(
        self,
        alarm_id: int,
        *,
        label: Optional[str] = None,
        enabled: Optional[bool] = None,
        oneoff_time: Optional[str] = None,
        recurring_time: Optional[str] = None,
        weekdays: Optional[List[int]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or self.now()
        alarm = self._get_alarm(alarm_id)

        if label is not None:
            alarm["label"] = str(label)
        if enabled is not None:
            alarm["enabled"] = bool(enabled)

        if alarm["kind"] == "oneoff" and oneoff_time is not None:
            alarm["oneoff_time"] = _iso(self._parse_datetime(oneoff_time))

        if alarm["kind"] == "recurring":
            if recurring_time is not None:
                self._parse_hhmm(recurring_time)
                alarm["recurring_time"] = recurring_time
            if weekdays is not None:
                clean_weekdays = sorted({int(day) for day in weekdays})
                if not clean_weekdays:
                    raise ValueError("weekdays cannot be empty")
                if any(day < 0 or day > 6 for day in clean_weekdays):
                    raise ValueError("weekdays must be 0..6")
                alarm["weekdays"] = clean_weekdays

        alarm["updated_at"] = _iso(now)
        return alarm

    def _pick_ringing_alarm(self, alarm_id: Optional[int]) -> int:
        if alarm_id is not None:
            if alarm_id not in self.ringing_alarm_ids:
                raise ValueError(f"alarm id {alarm_id} is not currently ringing")
            return alarm_id

        if not self.ringing_alarm_ids:
            raise ValueError("no alarm is currently ringing")
        return sorted(self.ringing_alarm_ids)[0]

    def dismiss(self, alarm_id: Optional[int] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.now()
        target_id = self._pick_ringing_alarm(alarm_id)
        alarm = self._get_alarm(target_id)
        self.ringing_alarm_ids.discard(target_id)

        if alarm["kind"] == "oneoff":
            alarm["enabled"] = False
        alarm["snooze_until"] = None
        alarm["updated_at"] = _iso(now)
        return alarm

    def snooze(
        self,
        alarm_id: Optional[int] = None,
        minutes: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or self.now()
        target_id = self._pick_ringing_alarm(alarm_id)
        alarm = self._get_alarm(target_id)

        snooze_minutes = minutes or self.default_snooze_minutes
        snooze_until = now + timedelta(minutes=snooze_minutes)
        alarm["snooze_until"] = _iso(snooze_until)
        alarm["updated_at"] = _iso(now)
        self.ringing_alarm_ids.discard(target_id)
        return alarm

    def set_timer(self, duration_seconds: int, label: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.now()
        if duration_seconds <= 0:
            raise ValueError("duration must be > 0")

        timer = {
            "id": self._next_id(),
            "label": label,
            "duration_seconds": int(duration_seconds),
            "remaining_seconds": int(duration_seconds),
            "ends_at": _iso(now + timedelta(seconds=duration_seconds)),
            "active": True,
            "created_at": _iso(now),
            "updated_at": _iso(now),
        }
        self.state["timers"].append(timer)
        return timer

    def cancel_timer(self, timer_id: int, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.now()
        timer = self._get_timer(timer_id)
        timer["active"] = False
        timer["updated_at"] = _iso(now)
        return timer

    def _recurring_time_today(self, alarm: Dict[str, Any], day: date) -> datetime:
        hour, minute = self._parse_hhmm(alarm["recurring_time"])
        return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=self.timezone)

    def _recurring_next_after(self, alarm: Dict[str, Any], now: datetime) -> Optional[datetime]:
        if not alarm["enabled"]:
            return None

        snooze_until = alarm.get("snooze_until")
        if snooze_until:
            candidate = self._parse_datetime(snooze_until)
            return candidate if candidate >= now else now

        weekdays = set(int(day) for day in alarm.get("weekdays", []))
        if not weekdays:
            return None

        for day_offset in range(8):
            day = (now + timedelta(days=day_offset)).date()
            if day.weekday() not in weekdays:
                continue
            candidate = self._recurring_time_today(alarm, day)
            if candidate >= now:
                return candidate
        return None

    def _alarm_next_fire(self, alarm: Dict[str, Any], now: datetime) -> Optional[datetime]:
        if not alarm.get("enabled", False):
            return None

        if int(alarm["id"]) in self.ringing_alarm_ids:
            return now

        if alarm["kind"] == "oneoff":
            candidate = self._parse_datetime(alarm["snooze_until"] or alarm["oneoff_time"])
            return candidate if candidate >= now else None

        if alarm["kind"] == "recurring":
            return self._recurring_next_after(alarm, now)

        return None

    def get_next_alarm(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        now = now or self.now()
        candidates: List[Tuple[datetime, Dict[str, Any]]] = []

        for alarm in self.state["alarms"]:
            fire_at = self._alarm_next_fire(alarm, now)
            if fire_at is not None:
                candidates.append((fire_at, alarm))

        if not candidates:
            return None

        fire_at, alarm = min(candidates, key=lambda item: item[0])
        return {
            "id": int(alarm["id"]),
            "label": alarm.get("label", ""),
            "kind": alarm["kind"],
            "when": _iso(fire_at),
        }

    def list_alarms(self) -> List[Dict[str, Any]]:
        return sorted(self.state["alarms"], key=lambda alarm: int(alarm["id"]))

    def list_timers(self) -> List[Dict[str, Any]]:
        return sorted(self.state["timers"], key=lambda timer: int(timer["id"]))

    def get_ringing_alarms(self) -> List[Dict[str, Any]]:
        by_id = {int(alarm["id"]): alarm for alarm in self.state["alarms"]}
        result: List[Dict[str, Any]] = []
        for alarm_id in sorted(self.ringing_alarm_ids):
            alarm = by_id.get(alarm_id)
            if alarm is None:
                continue
            result.append(
                {
                    "id": alarm_id,
                    "label": alarm.get("label", ""),
                    "kind": alarm.get("kind", "oneoff"),
                    "snooze_until": alarm.get("snooze_until"),
                }
            )
        return result

    def get_active_timers(self) -> List[Dict[str, Any]]:
        return [timer for timer in self.list_timers() if timer.get("active")]

    def tick(self, now: Optional[datetime] = None) -> Tuple[Dict[str, Any], bool]:
        now = now or self.now()
        changed = False
        events = {
            "alarms_triggered": [],
            "timers_finished": [],
        }

        for alarm in self.state["alarms"]:
            if not alarm.get("enabled", False):
                continue

            alarm_id = int(alarm["id"])
            if alarm_id in self.ringing_alarm_ids:
                continue

            if alarm["kind"] == "oneoff":
                due_at = self._parse_datetime(alarm["snooze_until"] or alarm["oneoff_time"])
                if now >= due_at:
                    self.ringing_alarm_ids.add(alarm_id)
                    alarm["last_triggered_at"] = _iso(now)
                    alarm["snooze_until"] = None
                    alarm["updated_at"] = _iso(now)
                    events["alarms_triggered"].append({
                        "id": alarm_id,
                        "kind": alarm["kind"],
                        "label": alarm.get("label", ""),
                        "triggered_at": _iso(now),
                    })
                    changed = True
                continue

            if alarm["kind"] == "recurring":
                snooze_until = alarm.get("snooze_until")
                if snooze_until:
                    due_at = self._parse_datetime(snooze_until)
                    should_fire = now >= due_at
                else:
                    weekdays = set(int(day) for day in alarm.get("weekdays", []))
                    if now.weekday() not in weekdays:
                        continue
                    due_at = self._recurring_time_today(alarm, now.date())
                    last_date = alarm.get("last_triggered_date")
                    should_fire = now >= due_at and last_date != now.date().isoformat()

                if should_fire:
                    self.ringing_alarm_ids.add(alarm_id)
                    alarm["last_triggered_at"] = _iso(now)
                    alarm["last_triggered_date"] = now.date().isoformat()
                    alarm["snooze_until"] = None
                    alarm["updated_at"] = _iso(now)
                    events["alarms_triggered"].append({
                        "id": alarm_id,
                        "kind": alarm["kind"],
                        "label": alarm.get("label", ""),
                        "triggered_at": _iso(now),
                    })
                    changed = True

        for timer in self.state["timers"]:
            if not timer.get("active", False):
                continue

            ends_at = self._parse_datetime(timer["ends_at"])
            remaining = max(0, int((ends_at - now).total_seconds()))
            if int(timer.get("remaining_seconds", -1)) != remaining:
                timer["remaining_seconds"] = remaining
                timer["updated_at"] = _iso(now)
                changed = True

            if remaining <= 0:
                timer["active"] = False
                timer["updated_at"] = _iso(now)
                events["timers_finished"].append(
                    {
                        "id": int(timer["id"]),
                        "label": timer.get("label", ""),
                        "finished_at": _iso(now),
                    }
                )
                changed = True

        return events, changed
