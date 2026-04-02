"""Configuration loading for the standalone alarm brain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class Config:
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic_prefix: str = "alarm_brain"
    mqtt_client_id: str = "alarm-brain"
    timezone: str = "UTC"
    data_file: str = "./alarm_data.json"
    tick_seconds: int = 1
    default_snooze_minutes: int = 10

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Config":
        return cls(
            mqtt_host=str(raw.get("mqtt_host", cls.mqtt_host)),
            mqtt_port=int(raw.get("mqtt_port", cls.mqtt_port)),
            mqtt_username=str(raw.get("mqtt_username", cls.mqtt_username)),
            mqtt_password=str(raw.get("mqtt_password", cls.mqtt_password)),
            mqtt_topic_prefix=str(raw.get("mqtt_topic_prefix", cls.mqtt_topic_prefix)).strip("/"),
            mqtt_client_id=str(raw.get("mqtt_client_id", cls.mqtt_client_id)),
            timezone=str(raw.get("timezone", cls.timezone)),
            data_file=str(raw.get("data_file", cls.data_file)),
            tick_seconds=max(1, int(raw.get("tick_seconds", cls.tick_seconds))),
            default_snooze_minutes=max(
                1, int(raw.get("default_snooze_minutes", cls.default_snooze_minutes))
            ),
        )

    @classmethod
    def load(cls, config_path: str | Path | None) -> "Config":
        if config_path is None:
            return cls()

        path = Path(config_path)
        if not path.exists():
            return cls()

        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls.from_dict(payload)
