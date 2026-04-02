"""Service loop and MQTT command handling for alarm-brain."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .config import Config
from .engine import AlarmEngine
from .mqtt_bridge import MqttBridge
from .storage import load_state, save_state


class AlarmBrainService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.data_path = Path(config.data_file)
        self.state: Dict[str, Any] = load_state(self.data_path)
        self.engine = AlarmEngine(
            state=self.state,
            timezone=ZoneInfo(config.timezone),
            default_snooze_minutes=config.default_snooze_minutes,
        )
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._running = True
        self.mqtt: MqttBridge | None = None

    def _save(self) -> None:
        save_state(self.data_path, self.state)

    def _topic_json(self, suffix: str, payload: Any, retain: bool = False) -> None:
        if self.mqtt is None:
            return
        self.mqtt.publish(suffix, json.dumps(payload, separators=(",", ":")), retain=retain)

    def _publish_state(self) -> None:
        next_alarm = self.engine.get_next_alarm()
        timers = self.engine.get_active_timers()
        ringing = self.engine.get_ringing_alarms()

        self._topic_json("state/next_alarm", next_alarm, retain=True)
        self._topic_json("state/timers", timers, retain=True)
        self._topic_json("state/alarms", self.engine.list_alarms(), retain=True)
        self._topic_json(
            "state/active_alarm",
            {"status": "ringing" if ringing else "idle", "alarms": ringing},
            retain=True,
        )

    def _publish_heartbeat(self) -> None:
        self._topic_json("state/heartbeat", {"ts": datetime.now().isoformat(timespec="seconds")})

    def _publish_command_result(self, command: str, ok: bool, detail: str = "") -> None:
        self._topic_json(
            "state/command_result",
            {"command": command, "ok": ok, "detail": detail, "ts": datetime.now().isoformat()},
        )

    def _parse_json(self, payload: str) -> Dict[str, Any]:
        if not payload.strip():
            return {}
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("payload must be a JSON object")
        return raw

    def _apply_command(self, command: str, payload: str) -> bool:
        data = self._parse_json(payload)
        changed = False

        if command == "alarm/set":
            kind = str(data.get("kind", "oneoff")).strip().lower()
            if kind == "oneoff":
                self.engine.add_oneoff(when=str(data["time"]), label=str(data.get("label", "")))
            elif kind == "recurring":
                self.engine.add_recurring(
                    hhmm=str(data["time"]),
                    weekdays=[int(d) for d in data.get("weekdays", [])],
                    label=str(data.get("label", "")),
                )
            else:
                raise ValueError("kind must be oneoff or recurring")
            changed = True

        elif command == "alarm/update":
            alarm_id = int(data["id"])
            self.engine.update_alarm(
                alarm_id,
                label=data.get("label"),
                enabled=data.get("enabled"),
                oneoff_time=data.get("time") if data.get("kind") == "oneoff" else None,
                recurring_time=data.get("time") if data.get("kind") == "recurring" else None,
                weekdays=[int(d) for d in data["weekdays"]] if "weekdays" in data else None,
            )
            changed = True

        elif command == "alarm/remove":
            removed = self.engine.remove_alarm(int(data["id"]))
            if not removed:
                raise ValueError("alarm id not found")
            changed = True

        elif command == "alarm/snooze":
            alarm_id = int(data["id"]) if "id" in data else None
            minutes = int(data["minutes"]) if "minutes" in data else None
            self.engine.snooze(alarm_id=alarm_id, minutes=minutes)
            changed = True

        elif command == "alarm/dismiss":
            alarm_id = int(data["id"]) if "id" in data else None
            self.engine.dismiss(alarm_id=alarm_id)
            changed = True

        elif command == "timer/set":
            self.engine.set_timer(int(data["duration_seconds"]), label=str(data.get("label", "")))
            changed = True

        elif command == "timer/cancel":
            self.engine.cancel_timer(int(data["id"]))
            changed = True

        elif command == "state/request":
            self._publish_state()
            self._publish_command_result(command, True, "state published")

        else:
            raise ValueError(f"unsupported command: {command}")

        if changed:
            self._save()
            self._publish_state()
            self._publish_command_result(command, True, "ok")

        return changed

    async def _run_loop(self) -> None:
        assert self.mqtt is not None

        self._save()
        self._publish_state()
        self.mqtt.publish("state/online", "true", retain=True)

        while self._running:
            try:
                command, payload = await asyncio.wait_for(
                    self.queue.get(), timeout=float(self.config.tick_seconds)
                )
                try:
                    self._apply_command(command, payload)
                except Exception as exc:  # noqa: BLE001
                    self._publish_command_result(command, False, str(exc))
                    self._topic_json("state/error", {"command": command, "error": str(exc)})
            except asyncio.TimeoutError:
                pass

            events, changed = self.engine.tick()
            if events["alarms_triggered"]:
                self._topic_json("state/alarm_triggered", events["alarms_triggered"])
            if events["timers_finished"]:
                self._topic_json("state/timer_finished", events["timers_finished"])
            if changed:
                self._save()
                self._publish_state()

            self._publish_heartbeat()

        self.mqtt.publish("state/online", "false", retain=True)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.mqtt = MqttBridge(
            loop=loop,
            queue=self.queue,
            host=self.config.mqtt_host,
            port=self.config.mqtt_port,
            topic_prefix=self.config.mqtt_topic_prefix,
            client_id=self.config.mqtt_client_id,
            username=self.config.mqtt_username,
            password=self.config.mqtt_password,
        )
        self.mqtt.connect_start()

        try:
            await self._run_loop()
        finally:
            if self.mqtt is not None:
                self.mqtt.stop()

    def stop(self) -> None:
        self._running = False
