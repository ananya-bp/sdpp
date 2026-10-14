# Phase 4 — Simulated data pipeline

**Everything under `ml/` is simulated.** No real KLE Tech student, application, or payment record
is used anywhere in this project. See `docs/DATA_DICTIONARY.md` for the full column-by-column
documentation, the exact assumptions behind every number, and how the data was validated.

## Setup

```bash
cd ml
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Generate the datasets

```bash
cd sdp-portal              # project root (not ml/)
python -m ml.make_datasets
```

Writes `ml/data/raw/`, `ml/data/labels/`, `ml/data/processed/`, and `ml/data/dataset_summary.json`
(generation config, per-file SHA-256 checksums, and the sanity-check numbers referenced in the
data dictionary). Same seed (`ml/config.py: SEED`) always produces byte-identical files — checked
by a test, not just assumed. Takes about 6 seconds for the full-size (3,000 student) run.

## Run the tests

```bash
cd ml
pytest        # expect: 8 passed, a few seconds (uses a small, fast configuration)
```

## Look at the data

```bash
python -m ml.make_figures    # writes 3 PNGs to ml/data/figures/
```

## Files

See `docs/DATA_DICTIONARY.md` §2 for the full file listing and what's in each one. In short:
`ml/config.py` (every generation assumption, in one place), `ml/simulate.py` (the world simulator),
`ml/features.py` (shared feature helpers), `ml/prepare.py` (raw → model-ready),
`ml/validate_datasets.py` (all correctness/leakage/sanity checks), `ml/make_datasets.py`
(orchestrates all of the above), `ml/make_figures.py` (optional plots), `ml/tests/` (pytest suite).

## For Phase 5

Read `docs/DATA_DICTIONARY.md` §6 and §8 before building any model — it documents exactly which
columns are features vs. labels, the oracle AUC ceiling for risk scoring, and a known limitation in
the anomaly data (a burst's first payment attempt cannot be flagged from that row alone).
