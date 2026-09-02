"""Deprecated entry point, kept so existing boot scripts keep working.

Prefer `python -m otradio` or the `otradio` command.
"""

from otradio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
