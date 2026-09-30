"""Adapt template text density and spacing for Chinese content."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import TypeAlias, cast

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)  # noqa: UP040 — build hosts may use Python 3.11


def prepare(checkout: Path) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != "2dcbde772ce46687c5c220f4e1e4886bdfe91cc9":
        raise ValueError("Unexpected Presenton revision")
    # Source fonts use Latin metrics. Tight line spacing overlaps CJK glyphs.
    for path in sorted((checkout / "templates").glob("*/template.json")):
        source = subprocess.check_output(
            [
                "git",
                "-C",
                str(checkout),
                "show",
                "HEAD:" + path.relative_to(checkout).as_posix(),
            ],
            text=True,
        )
        data = cast(JsonValue, json.loads(source))

        def adjust(value: JsonValue) -> None:
            if isinstance(value, dict):
                height = value.get("line_height")
                if isinstance(height, (int, float)) and 0 < height < 1.1:
                    value["line_height"] = 1.1
                minimum_key = (
                    "min_item_length"
                    if value.get("type") == "text-list"
                    else "min_length"
                )
                minimum = value.get(minimum_key)
                if (
                    value.get("type") in ("text", "text-list")
                    and isinstance(minimum, int)
                    and minimum > 1
                ):
                    # Latin character counts force verbose Chinese output.
                    value[minimum_key] = 1
                for child in value.values():
                    adjust(child)
            elif isinstance(value, list):
                for child in value:
                    adjust(child)

        adjust(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()
    prepare(args.checkout.resolve())
