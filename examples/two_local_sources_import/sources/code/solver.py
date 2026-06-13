from __future__ import annotations

import csv
import json
from pathlib import Path


def main() -> None:
    measurements = read_measurements(Path("sensor_a.csv"))
    calibration = json.loads(Path("calibration.json").read_text(encoding="utf-8"))

    scale = float(calibration["scale"])
    offset = float(calibration["offset"])
    corrected = [round(value * scale + offset, 3) for value in measurements]
    average = round(sum(corrected) / len(corrected), 3)

    Path("results").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    Path("results/report.txt").write_text(
        "\n".join(
            [
                "CalcChain two-source local import example",
                f"input_count={len(measurements)}",
                f"scale={scale}",
                f"offset={offset}",
                f"corrected_average={average}",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    Path("results/summary.json").write_text(
        json.dumps(
            {
                "input_count": len(measurements),
                "corrected_values": corrected,
                "corrected_average": average,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    Path("logs/solver.log").write_text("calculation completed\n", encoding="utf-8")


def read_measurements(path: Path) -> list[float]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return [float(row["value"]) for row in rows]


if __name__ == "__main__":
    main()
