from __future__ import annotations

from pathlib import Path

from dem.insar.snaphu import parse_snaphu_command


def test_parse_snaphu_command_uses_real_command_line(tmp_path: Path) -> None:
    conf = tmp_path / "snaphu.conf"
    conf.write_text(
        "\n".join(
            [
                "# CONFIG FOR SNAPHU",
                "# Command to call snaphu:",
                "#",
                "#       snaphu -f snaphu.conf Phase_ifg_IW1_VV_04Jun2024_16Jun2024.snaphu.img 22244",
                "",
                "STATCOSTMODE TOPO",
            ]
        ),
        encoding="utf-8",
    )

    assert parse_snaphu_command(conf) == [
        "snaphu",
        "-f",
        "snaphu.conf",
        "Phase_ifg_IW1_VV_04Jun2024_16Jun2024.snaphu.img",
        "22244",
    ]
