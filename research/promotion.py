from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def activate_paper_trial(
    artifact_dir: Path,
    holdout_report_path: Path,
    approved: bool = False,
) -> Dict[str, Any]:
    if not approved:
        raise ValueError("Explicit paper-trial approval is required.")
    metadata_path = artifact_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    report = json.loads(holdout_report_path.read_text(encoding="utf-8"))
    marker_path = Path(report.get("consumption_marker", ""))
    if not marker_path.is_file():
        raise ValueError("Final-holdout consumption marker is missing.")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    version = metadata.get("version")
    evaluations = [
        evaluation
        for evaluation in report.get("evaluations", [])
        if evaluation.get("candidate_version") == version
    ]
    if (
        report.get("automatic_promotion") is not False
        or marker.get("report_sha256")
        != hashlib.sha256(holdout_report_path.read_bytes()).hexdigest()
        or version not in marker.get("candidate_versions", [])
        or len(evaluations) != 1
        or evaluations[0].get("all_historical_gates_passed") is not True
        or not evaluations[0].get("gates")
        or not all(evaluations[0]["gates"].values())
    ):
        raise ValueError(
            "Candidate lacks a matching single-use final-holdout report with all historical gates passing."
        )
    if metadata.get("strategy") != "fallback":
        raise ValueError("Only candidates for the production fallback strategy may enter paper trial.")
    if metadata.get("promoted") or metadata.get("promotion_gate_passed"):
        raise ValueError("Candidate has already been promoted or activated.")

    metadata.update(
        {
            "promoted": True,
            "promotion_gate_passed": True,
            "lifecycle": "paper_trial",
            "paper_trial_started_at_utc": datetime.now(timezone.utc).isoformat(),
            "paper_trial_approval": "explicit operator approval",
            "final_holdout_report": str(holdout_report_path.resolve()),
            "final_holdout_range": {
                "start": report.get("holdout_start"),
                "end": report.get("holdout_end"),
            },
            "forward_validation_required": {
                "minimum_duration_days": 56,
                "minimum_closed_trades": 100,
            },
        }
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=metadata_path.parent,
        prefix=f"{metadata_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temporary = Path(temp_file.name)
        temp_file.write(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    try:
        os.replace(temporary, metadata_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Activate a historically qualified candidate for paper-only trial."
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--holdout-report",
        type=Path,
        default=Path("research/reports/final-holdout.json"),
    )
    parser.add_argument(
        "--approve-paper-trial",
        action="store_true",
        help="Explicitly authorize this model to make paper trades.",
    )
    args = parser.parse_args()
    metadata = activate_paper_trial(
        args.candidate,
        args.holdout_report,
        approved=args.approve_paper_trial,
    )
    print(
        f"Activated {metadata['version']} for paper trial only. "
        "This does not prove prospective performance or authorize real trading."
    )


if __name__ == "__main__":
    main()
