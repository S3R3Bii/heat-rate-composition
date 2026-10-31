"""Aggregate source components and test cohort support without heat-rate outcomes."""

import argparse, gzip, io, json
from collections import Counter
from pathlib import Path
from decompose_v2 import config, load_source, cells_from_source, support_qualification


def write(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Fresh qualification output required")
    a.out.mkdir(parents=True)
    cfg = config()
    source = load_source()
    cells, ledger, excluded = cells_from_source(source, cfg)
    support = support_qualification(cells, cfg)
    failed = [r for r in support if not r["primary_support_pass"]]
    payload = (json.dumps(ledger, indent=2) + "\n").encode()
    packed = io.BytesIO()
    with gzip.GzipFile(
        fileobj=packed, filename="", mode="wb", mtime=0, compresslevel=9
    ) as f:
        f.write(payload)
    (a.out / "group_ledger.json.gz").write_bytes(packed.getvalue())
    write(a.out / "excluded_source_rows.json", excluded)
    write(a.out / "case_support.json", support)
    counts = Counter((r["grain"], r["year"], r["reason"]) for r in ledger)
    summary = dict(
        status=(
            "FAIL_FIXED_PRIMARY_SUPPORT"
            if failed
            else "PASS_SOURCE_AGGREGATION_AND_FIXED_SUPPORT"
        ),
        source_rows=len(source),
        group_rows=len(ledger),
        group_counts=[
            dict(grain=g, year=y, reason=r, cells=n)
            for (g, y, r), n in sorted(counts.items())
        ],
        case_support_rows=len(support),
        primary_support_cases=sum(r["required_primary_support"] for r in support),
        failed_primary_support_cases=failed,
        empty_secondary_cases=sum(
            not r["matched_cells"] and not r["required_primary_support"]
            for r in support
        ),
        negative_source_generation_components_by_grain={
            g: sum(
                r["negative_generation_components"] for r in ledger if r["grain"] == g
            )
            for g in cfg["grain"]
        },
        original_v1_gate="FAILED_UNCHANGED",
        decomposition_outcomes_computed=False,
        ambiguous_quantities_aggregated=False,
        scope="Exact source sums and membership/support only; no fuel/generation ratios, within/mix or influence scores.",
    )
    write(a.out / "qualification.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "group_counts"}))
    if failed:
        raise RuntimeError(
            "Preserve fixed primary support failure; do not change cohort"
        )


if __name__ == "__main__":
    main()
