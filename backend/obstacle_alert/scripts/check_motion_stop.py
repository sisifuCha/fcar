#!/usr/bin/env python3
"""Safely check stop-command interfaces.

Default mode is dry-run. Use --execute to send only stop commands; this script
never starts movement by itself.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_rosmaster():
    try:
        from Rosmaster_Lib import Rosmaster
        return Rosmaster, "Rosmaster_Lib"
    except Exception:
        from control import Rosmaster
        return Rosmaster, "control.py"


def main():
    parser = argparse.ArgumentParser(description="Check stop commands without initiating motion.")
    parser.add_argument("--execute", action="store_true", help="Actually send stop commands to hardware.")
    parser.add_argument(
        "--method",
        choices=("motion", "run", "both"),
        default="both",
        help="Stop method to test. Default: both",
    )
    parser.add_argument("--debug", action="store_true", help="Enable Rosmaster debug output.")
    args = parser.parse_args()

    result = {
        "ok": False,
        "executed": bool(args.execute),
        "method": args.method,
        "backend": None,
        "commands": [],
        "error": None,
    }

    if not args.execute:
        result.update({
            "ok": True,
            "message": "dry-run only; add --execute to send stop command(s). The script never starts movement.",
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    bot = None
    try:
        Rosmaster, backend = load_rosmaster()
        result["backend"] = backend
        bot = Rosmaster(debug=args.debug)

        if args.method in ("motion", "both"):
            bot.set_car_motion(0, 0, 0)
            result["commands"].append("set_car_motion(0, 0, 0)")
        if args.method in ("run", "both"):
            bot.set_car_run(0, 0)
            result["commands"].append("set_car_run(0, 0)")

        result["ok"] = True
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        if bot is not None:
            del bot

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
