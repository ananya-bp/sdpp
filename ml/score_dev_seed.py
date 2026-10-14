"""Score the 12 development-seed students (backend/app/db/seed_students.py) with the saved risk model.

Reads the seed list straight from the source file (AST, no DB / backend import needed). The seed table holds only
department/semester/CGPA/backlogs/fee status, so everything else is a DOCUMENTED ASSUMPTION, not data:
  document_type=TRANSCRIPT, is_alumni=False, num_documents=1, OCR succeeded and matched the CGPA,
  prior_apps_count=0 and prior_review_count_lagged=0 (freshly seeded: no application history),
  past_fee_delays_12m = 0 if fee_status CLEAR else 1 (DUE now => at least 1 due month; a lower bound).
NOTE: DUE-fee students would be NOT_ELIGIBLE under the rule engine and never reach risk scoring in production.
They are scored here only to show how the model responds.
"""
import ast
from pathlib import Path

import pandas as pd

from .risk_scoring import predict_risk, review_flag_threshold

SEED_FILE = Path(__file__).resolve().parents[1] / "backend" / "app" / "db" / "seed_students.py"


def load_seed_students(path: Path = SEED_FILE) -> list[tuple]:
    tree = ast.parse(path.read_text())
    consts = {n.targets[0].id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}

    class Sub(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Constant(consts[node.id]), node)

    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SIMULATED_STUDENTS":
            return ast.literal_eval(ast.fix_missing_locations(Sub().visit(n.value)))
    raise RuntimeError("SIMULATED_STUDENTS not found")


def score_dev_seed() -> pd.DataFrame:
    rows = []
    for usn, _name, dept, sem, cgpa, backlogs, fee in load_seed_students():
        p = predict_risk(document_type="TRANSCRIPT", department=dept, semester=sem, cgpa=float(cgpa),
                         backlog_count=backlogs, past_fee_delays_12m=0 if fee == "CLEAR" else 1,
                         ocr_detected_cgpa=float(cgpa))
        rows.append({"usn": usn, "dept": dept.split()[0], "sem": sem, "cgpa": float(cgpa), "backlogs": backlogs,
                     "fee": fee, "risk_prob": round(p, 4), "above_flag_thr": p >= review_flag_threshold()})
    return pd.DataFrame(rows).sort_values("risk_prob").reset_index(drop=True)


if __name__ == "__main__":
    print(score_dev_seed().to_string())
    print("flag threshold:", review_flag_threshold())
