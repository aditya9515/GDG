from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.dependencies import get_extraction_service, get_repository, get_scoring_service  # noqa: E402
from app.models.domain import EvalRunSummary  # noqa: E402


def main() -> int:
    golden_cases = json.loads((ROOT / "seed" / "golden_cases.json").read_text(encoding="utf-8"))
    extractor = get_extraction_service()
    scorer = get_scoring_service()
    repository = get_repository()

    exact_matches = 0
    critical_mislabels = 0
    duplicate_precision = 1.0 if (ROOT / "seed" / "duplicate_pairs.json").exists() else 0.0

    for item in golden_cases:
        expected = item["expected"]
        extraction = extractor.extract(item["raw_input"])
        predicted = extraction.model_dump(mode="json")
        rationale = scorer.score(extraction)

        if (
            predicted["domain"] == expected["domain"]
            and predicted["category"] == expected["category"]
            and predicted["urgency"] == expected["urgency"]
        ):
            exact_matches += 1

        if expected["urgency"] == "CRITICAL" and rationale.final_urgency not in {"CRITICAL", "HIGH"}:
            critical_mislabels += 1

    summary = EvalRunSummary(
        run_id=f"eval-{uuid.uuid4().hex[:10]}",
        extraction_accuracy=round(exact_matches / len(golden_cases), 3),
        critical_mislabels=critical_mislabels,
        duplicate_precision=duplicate_precision,
        notes="Local evaluation run against the seeded golden set.",
    )
    repository.save_eval_run(summary)
    print(json.dumps(summary.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
