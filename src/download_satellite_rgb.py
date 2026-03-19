# -*- coding: utf-8 -*-
"""
RGB/NIR загрузчик (оптические спутники).

Целевое имя входного CLI:
- `src/download_satellite_rgb.py`
"""

from download_satellite import build_parser


def main() -> None:
    parser = build_parser()
    parser.prog = "download_satellite_rgb"
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

