# alarm-brain

Standalone local alarm scheduler with JSON persistence and 2-way MQTT control.

## Design goals

- Fully local and deterministic
- Separate from the rest of the repository runtime
- JSON persistence with atomic writes
- MQTT bidirectional control for Home Assistant front-end
- Recurring alarms remain enabled after dismiss

## Quick start

```bash
cd alarm-brain
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run daemon mode:

```bash
alarm-brain --config config.example.json run
```

Use local CLI commands for testing:

```bash
alarm-brain --config config.example.json add-oneoff --time 2026-03-27T07:30:00 --label Wake
alarm-brain --config config.example.json add-recurring --time 07:00 --weekdays 0,1,2,3,4 --label Work
alarm-brain --config config.example.json list-alarms
alarm-brain --config config.example.json show-next
```

## MQTT topics

Prefix comes from `mqtt_topic_prefix` in config (default `alarm_brain`).

Commands to publish to:

- `<prefix>/cmd/alarm/set`
- `<prefix>/cmd/alarm/update`
- `<prefix>/cmd/alarm/remove`
- `<prefix>/cmd/alarm/snooze`
- `<prefix>/cmd/alarm/dismiss`
- `<prefix>/cmd/timer/set`
- `<prefix>/cmd/timer/cancel`
- `<prefix>/cmd/state/request`

State topics published by service:

- `<prefix>/state/online` (retained, `true`/`false`)
- `<prefix>/state/next_alarm` (retained JSON object or null)
- `<prefix>/state/alarms` (retained JSON list)
- `<prefix>/state/timers` (retained JSON list)
- `<prefix>/state/active_alarm` (retained status + ringing list)
- `<prefix>/state/alarm_triggered` (event list)
- `<prefix>/state/timer_finished` (event list)
- `<prefix>/state/command_result` (command ack with success/error)
- `<prefix>/state/error` (error detail)
- `<prefix>/state/heartbeat` (periodic timestamp)

### Command payload examples

Set one-off alarm:

```json
{
  "kind": "oneoff",
  "time": "2026-03-27T07:30:00",
  "label": "Wake"
}
```

Set recurring alarm:

```json
{
  "kind": "recurring",
  "time": "07:00",
  "weekdays": [0, 1, 2, 3, 4],
  "label": "Work"
}
```

Snooze currently ringing alarm:

```json
{
  "minutes": 10
}
```

Set timer:

```json
{
  "duration_seconds": 300,
  "label": "Tea"
}
```

## Config

Copy and edit `config.example.json`.

- `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`
- `mqtt_topic_prefix`, `mqtt_client_id`
- `timezone` (IANA name, e.g. `Europe/Stockholm`)
- `data_file`
- `tick_seconds` (recommended 1)
- `default_snooze_minutes`

## Behavior notes

- Dismissing a one-off alarm disables it.
- Dismissing a recurring alarm only clears the active ring; the alarm remains enabled for future days.
- JSON state is written on every mutation and scheduler change.
