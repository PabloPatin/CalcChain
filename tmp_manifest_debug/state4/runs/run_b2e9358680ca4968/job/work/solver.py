from pathlib import Path
import json


def main() -> None:
    input_root = Path("input")
    values = []
    for path in sorted(input_root.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            values.append(int(text))

    total = sum(values)
    results = Path("results")
    logs = Path("logs")
    results.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    (results / "report.txt").write_text(f"values={values}\ntotal={total}\n", encoding="utf-8")
    (results / "summary.json").write_text(
        json.dumps({"values": values, "total": total}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (logs / "solver.log").write_text("solver completed\n", encoding="utf-8")
    print(f"total={total}")


if __name__ == "__main__":
    main()
