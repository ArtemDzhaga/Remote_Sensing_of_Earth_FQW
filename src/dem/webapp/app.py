# -*- coding: utf-8 -*-
"""Заготовка Streamlit UI; установите: pip install -e .[viz]"""

from __future__ import annotations


def main() -> None:
    try:
        import streamlit as st  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "Установите streamlit: pip install streamlit  или  pip install -e .[viz]"
        ) from e
    raise SystemExit("Заполните страницы (регион, инвентарь сцен, отчёты validate_dem).")


if __name__ == "__main__":
    main()
