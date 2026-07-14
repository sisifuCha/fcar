#!/usr/bin/env python3
"""Safely check the Rosmaster buzzer interface.

Default mode is dry-run. Use --execute to make the buzzer beep.
"""

import argparse
import json
import sys
import time
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
    parser = argparse.ArgumentParser(description="Check buzzer by calling Rosmaster.set_beep().")
    parser.add_argument("--execute", action="store_true", help="Actually send beep commands to hardware.")
    parser.add_argument("--duration", type=int, default=60, help="Beep duration in ms. Default: 60")
    parser.add_argument("--debug", action="store_true", help="Enable Rosmaster debug output.")
    args = parser.parse_args()

    result = {
        "ok": False,
        "executed": bool(args.execute),
        "duration": args.duration,
        "backend": None,
        "commands": [],
        "error": None,
    }

    if not args.execute:
        result.update({
            "ok": True,
            "message": "dry-run only; add --execute to call set_beep(duration) then set_beep(0)",
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    bot = None
    try:
        Rosmaster, backend = load_rosmaster()
        result["backend"] = backend
        bot = Rosmaster(debug=args.debug)
        bot.set_beep(args.duration)
        result["commands"].append(f"set_beep({args.duration})")
        time.sleep(max(args.duration / 1000.0, 0.1))
        bot.set_beep(0)
        result["commands"].append("set_beep(0)")
        result["ok"] = True
    except Exception as exc:
        result["error"] = repr(exc)
        try:
            if bot is not None:
                bot.set_beep(0)
                result["commands"].append("set_beep(0) after error")
        except Exception:
            pass
    finally:
        if bot is not None:
            del bot

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
