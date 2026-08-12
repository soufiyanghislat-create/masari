#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from classifiability import evaluate_classifiable_coverage


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit Masari classifiable taxonomy coverage")
    ap.add_argument("--index", required=True)
    ap.add_argument("--min-coverage", type=float, default=90.0)
    args = ap.parse_args()

    data = json.loads(Path(args.index).read_text(encoding="utf-8"))
    report = evaluate_classifiable_coverage(
        data.get("jobs", []),
        minimum_coverage_pct=args.min_coverage,
    )

    visible = {k: v for k, v in report.items() if not k.endswith("_rows")}
    visible["gate"] = "PASS" if report["gate"] else "FAIL"

    print("=== MASARI CLASSIFIABILITY AUDIT v2.8 ===")
    print(json.dumps(visible, ensure_ascii=False, indent=2))

    if report["unexplained_unclassified_rows"]:
        print("\n=== UNEXPLAINED UNCLASSIFIED ===")
        print(json.dumps(report["unexplained_unclassified_rows"], ensure_ascii=False, indent=2))

    if report["ambiguous_classified_rows"]:
        print("\n=== AMBIGUOUS BUT CLASSIFIED (UNSAFE) ===")
        print(json.dumps(report["ambiguous_classified_rows"], ensure_ascii=False, indent=2))

    print("MASARI_CLASSIFIABILITY_GATE=" + ("PASS" if report["gate"] else "FAIL"))
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
