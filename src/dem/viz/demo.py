# -*- coding: utf-8 -*-
"""
Единая точка входа для демо: подкоманды ``progress`` и ``fetch-rtc``.

Реализации: ``demo_progress``, ``fetch_rtc_bundle``.
"""

from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            """dem.viz.demo — обёртка над демо-скриптами.

Использование:
  python -m dem.viz.demo progress [аргументы demo_progress ...]
  python -m dem.viz.demo fetch-rtc [аргументы fetch_rtc_bundle ...]

Эквивалентно:
  python -m dem.viz.demo_progress ...
  python -m dem.viz.fetch_rtc_bundle ...
"""
        )
        return

    sub = argv.pop(0)
    sys.argv = [sys.argv[0]] + argv

    if sub == "progress":
        from dem.viz.demo_progress import main as run

        run()
    elif sub in ("fetch-rtc", "fetch_rtc"):
        from dem.viz.fetch_rtc_bundle import main as run

        run()
    else:
        raise SystemExit(f"Неизвестная подкоманда: {sub}. Ожидалось: progress | fetch-rtc")


if __name__ == "__main__":
    main()
