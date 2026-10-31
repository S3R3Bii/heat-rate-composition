"""Inspect a saved reported-ratio bridge without inferring engineering performance."""

import argparse, json
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assess(row):
    if row.get("state") != "ESTIMABLE":
        return dict(
            status="UNAVAILABLE_CASE",
            interpretation="Keep the unavailable case and its reason; no zero contribution is inferred.",
        )
    try:
        with localcontext() as context:
            context.prec = 100
            values = {
                k: Decimal(row[k])
                for k in [
                    "within",
                    "mix",
                    "outside_cohort_composition_remainder",
                    "full_change",
                ]
            }
            if not all(v.is_finite() for v in values.values()):
                raise ValueError("Nonfinite supplied component")
            residual = (
                values["within"]
                + values["mix"]
                + values["outside_cohort_composition_remainder"]
                - values["full_change"]
            )
            if abs(residual) > Decimal("1e-45"):
                return dict(
                    status="FAIL_SUPPLIED_BRIDGE",
                    residual=str(residual),
                    interpretation="Reconcile the components and denominator before describing this change.",
                )
            return dict(
                status="PASS_SUPPLIED_BRIDGE",
                components={k: str(v) for k, v in values.items()},
                units="MMBtu per MWh",
                within_and_mix_oppose=values["within"] * values["mix"] < 0,
                interpretation="Read within, mix, matching coverage and influence together. This is a reported-data identity; within is not proof of physical engineering improvement and the remainder is not plant entry/retirement.",
                scope="Offline saved-result review, not source authentication, an operational recommendation or a savings estimate.",
            )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return dict(
            status="UNAVAILABLE_COMPONENTS",
            interpretation="Complete finite components are required; no missing value is imputed.",
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--end-year", type=int, choices=list(range(2019, 2025)), default=2024
    )
    p.add_argument(
        "--fleet", choices=["coal", "natural_gas", "pooled"], default="pooled"
    )
    p.add_argument(
        "--grain", choices=["plant_fuel", "plant_technology_fuel"], default="plant_fuel"
    )
    p.add_argument(
        "--cohort", choices=["pair_common", "balanced_2018_2024"], default="pair_common"
    )
    a = p.parse_args()
    phase = "development" if a.end_year <= 2021 else "held"
    rows = json.loads((ROOT / f"results/v2/{phase}/cases.json").read_bytes())
    row = next(
        r
        for r in rows
        if r["end_year"] == a.end_year
        and r["fleet"] == a.fleet
        and r["grain"] == a.grain
        and r["cohort"] == a.cohort
    )
    print(json.dumps(dict(case_id=row["case_id"], **assess(row)), indent=2))


if __name__ == "__main__":
    main()
