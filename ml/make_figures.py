"""Render a few sanity-check plots from the generated datasets (not used by any model).

    python -m ml.make_figures

Writes PNGs to ml/data/figures/. Purely for a human to eyeball that the data looks like a
plausible university workflow before Phase 5 builds anything on top of it.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "figures"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    fc = pd.read_csv(DATA / "processed" / "forecast_daily.csv", parse_dates=["date"])
    daily_total = fc.groupby("date")["applications_submitted"].sum()
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(daily_total.index, daily_total.values, linewidth=0.5, alpha=0.5, label="daily total")
    ax.plot(daily_total.index, daily_total.rolling(28).mean(), linewidth=1.8, label="28-day rolling mean")
    ax.set_title("Simulated daily application volume, all document types")
    ax.set_ylabel("applications / day")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "daily_volume.png", dpi=130)
    plt.close(fig)

    tat = pd.read_csv(DATA / "processed" / "tat_applications.csv")
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.hist(tat["tat_hours"].clip(upper=tat["tat_hours"].quantile(0.99)), bins=60)
    ax.set_title("Turnaround time, verified applications (99th pct clipped)")
    ax.set_xlabel("hours")
    fig.tight_layout()
    fig.savefig(OUT / "tat_distribution.png", dpi=130)
    plt.close(fig)

    labels = pd.read_csv(DATA / "labels" / "application_labels.csv")
    d = labels.dropna(subset=["sim_true_review_probability"])
    fig, ax = plt.subplots(figsize=(6, 3.2))
    for val, name in ((0, "not flagged"), (1, "flagged for review")):
        ax.hist(d.loc[d["needs_manual_review"] == val, "sim_true_review_probability"], bins=40, alpha=0.6, label=name)
    ax.set_title("True review probability, by sampled label")
    ax.set_xlabel("sim_true_review_probability (label-only, never a feature)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "risk_label_separation.png", dpi=130)
    plt.close(fig)

    print(f"wrote 3 PNGs to {OUT}")


if __name__ == "__main__":
    main()
