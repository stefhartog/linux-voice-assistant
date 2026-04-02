"""CLI for running and testing alarm-brain locally."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

from .config import Config
from .engine import AlarmEngine
from .service import AlarmBrainService
from .storage import load_state, save_state


def _load_engine(config: Config) -> tuple[AlarmEngine, Path, dict]:
    data_path = Path(config.data_file)
    state = load_state(data_path)
    engine = AlarmEngine(
        state=state,
        timezone=ZoneInfo(config.timezone),
        default_snooze_minutes=config.default_snooze_minutes,
    )
    return engine, data_path, state


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone local alarm brain")
    parser.add_argument("--config", default=None, help="Path to JSON config file")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run service loop with MQTT")

    add_oneoff = sub.add_parser("add-oneoff", help="Add a one-off alarm")
    add_oneoff.add_argument("--time", required=True, help="ISO datetime")
    add_oneoff.add_argument("--label", default="", help="Optional alarm label")

    add_rec = sub.add_parser("add-recurring", help="Add a recurring alarm")
    add_rec.add_argument("--time", required=True, help="HH:MM")
    add_rec.add_argument("--weekdays", required=True, help="Comma-separated weekdays 0..6")
    add_rec.add_argument("--label", default="", help="Optional alarm label")

    rem_alarm = sub.add_parser("remove-alarm", help="Remove alarm by id")
    rem_alarm.add_argument("--id", required=True, type=int)

    update_alarm = sub.add_parser("update-alarm", help="Update alarm fields")
    update_alarm.add_argument("--id", required=True, type=int)
    update_alarm.add_argument("--label", default=None)
    update_alarm.add_argument("--enabled", choices=["true", "false"], default=None)
    update_alarm.add_argument("--time", default=None)
    update_alarm.add_argument("--weekdays", default=None)

    snooze = sub.add_parser("snooze", help="Snooze currently ringing alarm")
    snooze.add_argument("--id", type=int, default=None)
    snooze.add_argument("--minutes", type=int, default=None)

    dismiss = sub.add_parser("dismiss", help="Dismiss currently ringing alarm")
    dismiss.add_argument("--id", type=int, default=None)

    set_timer = sub.add_parser("set-timer", help="Set countdown timer")
    set_timer.add_argument("--seconds", required=True, type=int)
    set_timer.add_argument("--label", default="")

    cancel_timer = sub.add_parser("cancel-timer", help="Cancel timer by id")
    cancel_timer.add_argument("--id", required=True, type=int)

    sub.add_parser("list-alarms", help="List all alarms")
    sub.add_parser("list-timers", help="List all timers")
    sub.add_parser("show-next", help="Show next alarm")
    sub.add_parser("tick", help="Run one local scheduler tick")

    return parser


def _parse_weekdays(raw: str) -> List[int]:
    return [int(piece.strip()) for piece in raw.split(",") if piece.strip()]


def _run_local_command(args: argparse.Namespace, config: Config) -> int:
    engine, data_path, state = _load_engine(config)
    changed = False

    if args.command == "add-oneoff":
        alarm = engine.add_oneoff(args.time, args.label)
        _print_json(alarm)
        changed = True

    elif args.command == "add-recurring":
        alarm = engine.add_recurring(args.time, _parse_weekdays(args.weekdays), args.label)
        _print_json(alarm)
        changed = True

    elif args.command == "remove-alarm":
        changed = engine.remove_alarm(args.id)
        _print_json({"removed": changed, "id": args.id})

    elif args.command == "update-alarm":
        enabled = None if args.enabled is None else args.enabled == "true"
        weekdays = _parse_weekdays(args.weekdays) if args.weekdays else None
        alarm = engine.update_alarm(
            args.id,
            label=args.label,
            enabled=enabled,
            oneoff_time=args.time,
            recurring_time=args.time,
            weekdays=weekdays,
        )
        _print_json(alarm)
        changed = True

    elif args.command == "snooze":
        alarm = engine.snooze(alarm_id=args.id, minutes=args.minutes)
        _print_json(alarm)
        changed = True

    elif args.command == "dismiss":
        alarm = engine.dismiss(alarm_id=args.id)
        _print_json(alarm)
        changed = True

    elif args.command == "set-timer":
        timer = engine.set_timer(args.seconds, args.label)
        _print_json(timer)
        changed = True

    elif args.command == "cancel-timer":
        timer = engine.cancel_timer(args.id)
        _print_json(timer)
        changed = True

    elif args.command == "list-alarms":
        _print_json(engine.list_alarms())

    elif args.command == "list-timers":
        _print_json(engine.list_timers())

    elif args.command == "show-next":
        _print_json(engine.get_next_alarm())

    elif args.command == "tick":
        events, did_change = engine.tick()
        _print_json({"events": events, "changed": did_change})
        changed = did_change

    if changed:
        save_state(data_path, state)

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = Config.load(args.config)

    if args.command == "run":
        service = AlarmBrainService(config)
        try:
            asyncio.run(service.run())
        except KeyboardInterrupt:
            service.stop()
        return 0

    try:
        return _run_local_command(args, config)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
