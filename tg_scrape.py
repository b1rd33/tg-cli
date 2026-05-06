"""Deprecated entrypoint — kept so old muscle memory still works.

Use ``./tg <subcmd>`` or ``python -m tgcli <subcmd>`` instead.
"""
from __future__ import annotations

import sys

from tgcli.__main__ import main

if __name__ == "__main__":
    print(
        "tg_scrape.py is deprecated; run via `./tg <subcmd>` or `python -m tgcli <subcmd>`.",
        file=sys.stderr,
    )
    sys.exit(main())
