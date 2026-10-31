"""Retain every fixed decomposition case, contribution and primary plant deletion."""

import argparse, csv, gzip, io, json, platform, time
from decimal import Decimal
from pathlib import Path

from decompose_v2 import (
    ROOT,
    config,
    load_source,
    cells_from_source,
    case,
    check_freeze,
)


def write(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode())


def csv_gzip(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    stream = io.StringIO(newline="")
    w = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    packed = io.BytesIO()
    with gzip.GzipFile(
        fileobj=packed, filename="", mode="wb", mtime=0, compresslevel=9
    ) as handle:
        handle.write(stream.getvalue().encode())
    path.write_bytes(packed.getvalue())


def analyze(phase, out):
    if phase == "held":
        check_freeze()
    cfg = config()
    source = load_source()
    cells, ledger, excluded = cells_from_source(source, cfg)
    stored = json.loads(
        gzip.decompress((ROOT / "data/v2/group_ledger.json.gz").read_bytes())
    )
    assert stored == ledger
    qualification = json.loads((ROOT / "data/v2/qualification.json").read_bytes())
    assert (
        qualification["status"] == "PASS_SOURCE_AGGREGATION_AND_FIXED_SUPPORT"
        and not qualification["failed_primary_support_cases"]
    )
    ends = (
        cfg["development_pair_end_years"]
        if phase == "development"
        else cfg["held_pair_end_years"]
    )
    results = []
    contributions = []
    deletions = []
    runtimes = []
    for end in ends:
        for fleet in cfg["fleets"]:
            for grain in cfg["grain"]:
                for cohort in cfg["cohorts"]:
                    start = time.perf_counter()
                    result, contrib, influence = case(
                        cells, cfg, end, fleet, grain, cohort
                    )
                    runtimes.append(
                        dict(
                            case_id=result["case_id"],
                            elapsed_seconds=time.perf_counter() - start,
                        )
                    )
                    results.append(result)
                    contributions += contrib
                    deletions += influence
    assert len(results) == 36
    primary = [
        r
        for r in results
        if r["grain"] == "plant_fuel" and r["cohort"] == "pair_common"
    ]
    assert len(primary) == 9
    influence_ranges = []
    for result in primary:
        rows = [r for r in deletions if r["case_id"] == result["case_id"]]
        valid = [r for r in rows if r["state"] == "ESTIMABLE"]
        intervals = {}
        for field in ["within", "mix", "matched_change"]:
            values = [Decimal(r[field]) for r in valid]
            intervals[field] = dict(
                minimum=None if not values else str(min(values)),
                maximum=None if not values else str(max(values)),
            )
        influence_ranges.append(
            dict(
                case_id=result["case_id"],
                deletions=len(rows),
                estimable_deletions=len(valid),
                ranges=intervals,
                meaning="Finite leave-one-plant influence range, not a confidence interval",
            )
        )
    write(out / "cases.json", results)
    csv_gzip(out / "contributions.csv.gz", contributions)
    csv_gzip(out / "plant_deletions.csv.gz", deletions)
    write(out / "influence_ranges.json", influence_ranges)
    summary = dict(
        status=(
            "EXECUTED_FIXED_V2_DEVELOPMENT"
            if phase == "development"
            else "EXECUTED_FROZEN_V2_HELD_DECOMPOSITIONS"
        ),
        phase=phase,
        cases=len(results),
        estimable_cases=sum(r["state"] == "ESTIMABLE" for r in results),
        primary_cases=primary,
        cell_contributions=len(contributions),
        plant_deletions=len(deletions),
        precision_digits=60,
        units="MMBtu per MWh",
        original_v1_gate="FAILED_UNCHANGED",
        scope="Historical source-conditional algebraic identity on an explicitly unambiguous reporting cohort; no prediction, engineering efficiency or causal allocation claim",
        new_selection_made=False,
    )
    write(out / "summary.json", summary)
    write(
        out / "runtime.json",
        dict(
            python=platform.python_version(),
            per_case=runtimes,
            scope="Measured local execution; variable replay timing, not a production performance benchmark",
        ),
    )
    print(
        json.dumps({k: v for k, v in summary.items() if k != "primary_cases"}),
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["development", "held"], required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.phase == "held":
        check_freeze()
    if a.out.exists():
        raise ValueError("Fresh output required; preserve prior execution")
    a.out.mkdir(parents=True)
    analyze(a.phase, a.out)
