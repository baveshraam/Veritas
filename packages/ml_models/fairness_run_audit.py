"""Pre-demo bias audit. Run by hand or in CI — never on a request path.

    python packages/ml_models/fairness_run_audit.py
"""
import json
import sys

from ml_models.serving import run_fairness_audit

if __name__ == "__main__":
    failed = False
    for model in ("score_risk", "predict_recidivism"):
        report = run_fairness_audit(model)
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        if report.disparate_impact_flagged:
            print(f"!! {model}: disparate impact flagged — do not ship this model as-is")
            failed = True
    sys.exit(1 if failed else 0)
