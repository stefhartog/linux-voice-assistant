"""Thread-safe MQTT bridge for command ingest and state publishing."""

from __future__ import annotations

import asyncio
from typing import Optional, Tuple

import paho.mqtt.client as mqtt


class MqttBridge:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[Tuple[str, str]],
        host: str,
        port: int,
        topic_prefix: str,
        client_id: str,
        username: str = "",
        password: str = "",
    ) -> None:
        self.loop = loop
        self.queue = queue
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix.strip("/")

        # Keep compatibility with both paho-mqtt 1.x and 2.x.
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id=client_id)

        if username:
            self.client.username_pw_set(username=username, password=password or None)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _topic(self, suffix: str) -> str:
        return f"{self.topic_prefix}/{suffix.lstrip('/')}"

    def _on_connect(self, client, userdata, flags, rc, properties=None):  # noqa: ANN001
        if rc == 0:
            client.subscribe(self._topic("cmd/#"))

    def _on_message(self, client, userdata, msg):  # noqa: ANN001
        command_prefix = self._topic("cmd/")
        if not msg.topic.startswith(command_prefix):
            return

        command = msg.topic[len(command_prefix) :]
        payload = msg.payload.decode("utf-8") if msg.payload else ""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (command, payload))

    def connect_start(self) -> None:
        self.client.will_set(self._topic("state/online"), payload="false", retain=True)
        self.client.connect(self.host, self.port)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, suffix: str, payload: str, retain: bool = False, qos: int = 0) -> None:
        self.client.publish(self._topic(suffix), payload=payload, qos=qos, retain=retain)
