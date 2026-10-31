"""Independent 80-digit direct paths, bridge and complete plant-deletion checks."""

import argparse, csv, gzip, hashlib, json, subprocess, sys
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO = Decimal(0)
TWO = Decimal(2)
TOLERANCE = Decimal("1e-45")


class Check:
    def __init__(self):
        self.conditions = 0
        self.maximum = ZERO

    def exact(self, a, b, label):
        assert a == b, (label, a, b)
        self.conditions += 1

    def numeric(self, a, b, label):
        aa = Decimal(a)
        bb = Decimal(b)
        assert aa.is_finite() and bb.is_finite()
        error = abs(aa - bb)
        assert error <= TOLERANCE, (label, aa, bb, error)
        self.maximum = max(self.maximum, error)
        self.conditions += 1


def csv_rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check(phase, out):
    cfg = json.loads((ROOT / "protocol_v2.json").read_bytes())
    if phase == "held":
        fpath = ROOT / "data/v2/frozen_dependencies.json"
        assert fpath.exists()
        frozen = json.loads(fpath.read_bytes())
        assert (
            subprocess.check_output(
                ["git", "show", "HEAD:data/v2/frozen_dependencies.json"], cwd=ROOT
            )
            == fpath.read_bytes()
        )
        for n, d in frozen["dependencies"].items():
            assert hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == d, n
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "src/verify_grouping_v2.py"),
            "--out",
            str(ROOT / "data/v2"),
        ],
        cwd=ROOT,
        check=True,
    )
    ledger = json.loads(
        gzip.decompress((ROOT / "data/v2/group_ledger.json.gz").read_bytes())
    )
    group = {(r["grain"], r["year"], r["key"]): r for r in ledger}
    c = Check()
    results = json.loads((out / "cases.json").read_bytes())
    contributions = csv_rows(out / "contributions.csv.gz")
    influence = csv_rows(out / "plant_deletions.csv.gz")
    contrib_by = defaultdict(dict)
    influence_by = defaultdict(dict)
    for r in contributions:
        c.exact(r["key"] in contrib_by[r["case_id"]], False, "unique cell contribution")
        contrib_by[r["case_id"]][r["key"]] = r
    for r in influence:
        c.exact(
            r["removed_plant"] in influence_by[r["case_id"]],
            False,
            "unique plant deletion",
        )
        influence_by[r["case_id"]][r["removed_plant"]] = r
    ends = (
        cfg["development_pair_end_years"]
        if phase == "development"
        else cfg["held_pair_end_years"]
    )
    expected_ids = {
        f"{e-1}-{e}__{f}__{g}__{h}"
        for e in ends
        for f in cfg["fleets"]
        for g in cfg["grain"]
        for h in cfg["cohorts"]
    }
    c.exact(
        {r["case_id"] for r in results}, expected_ids, "complete fixed case lattice"
    )
    c.exact(len(results), 36, "case count")
    c.exact(set(contrib_by), expected_ids, "no extra or omitted contribution cases")
    c.exact(
        set(influence_by),
        {
            f"{e-1}-{e}__{f}__plant_fuel__pair_common"
            for e in ends
            for f in cfg["fleets"]
        },
        "only declared primary influence cases",
    )
    all_influence = 0
    direct_checks = 0
    with localcontext() as context:
        context.prec = 80
        for result in results:
            cid = result["case_id"]
            end = result["end_year"]
            start = end - 1
            fleet = result["fleet"]
            grain = result["grain"]
            cohort = result["cohort"]
            eligible = {
                y: {
                    k: r
                    for (g, yy, k), r in group.items()
                    if g == grain
                    and yy == y
                    and r["eligible"]
                    and (fleet == "pooled" or r["fuel_group"] == fleet)
                }
                for y in cfg["years"]
            }
            years = [start, end] if cohort == "pair_common" else cfg["years"]
            keys = sorted(set.intersection(*(set(eligible[y]) for y in years)))
            plants = sorted({eligible[start][k]["plant"] for k in keys}, key=int)
            for field, want in [
                ("start_year", start),
                ("matched_cells", len(keys)),
                ("matched_plants", len(plants)),
            ]:
                c.exact(result[field], want, field)
            c.exact(
                result["state"],
                "ESTIMABLE" if keys else "NOT_ESTIMABLE",
                "case availability",
            )
            if not keys:
                continue
            f0 = sum((Decimal(eligible[start][k]["fuel_mmbtu"]) for k in keys), ZERO)
            g0 = sum((Decimal(eligible[start][k]["net_mwh"]) for k in keys), ZERO)
            f1 = sum((Decimal(eligible[end][k]["fuel_mmbtu"]) for k in keys), ZERO)
            g1 = sum((Decimal(eligible[end][k]["net_mwh"]) for k in keys), ZERO)
            totals = {
                y: (
                    sum((Decimal(r["fuel_mmbtu"]) for r in eligible[y].values()), ZERO),
                    sum((Decimal(r["net_mwh"]) for r in eligible[y].values()), ZERO),
                )
                for y in [start, end]
            }
            hm0, hm1 = f0 / g0, f1 / g1
            h0full, h1full = [totals[y][0] / totals[y][1] for y in [start, end]]
            for field, want in [
                ("matched_fuel0", f0),
                ("matched_generation0", g0),
                ("matched_fuel1", f1),
                ("matched_generation1", g1),
                ("full_fuel0", totals[start][0]),
                ("full_generation0", totals[start][1]),
                ("full_fuel1", totals[end][0]),
                ("full_generation1", totals[end][1]),
            ]:
                c.exact(Decimal(result[field]), want, field)
            c.exact(set(contrib_by[cid]), set(keys), "all matched cells retained")
            sums = defaultdict(lambda: ZERO)
            native = {}
            byplant = defaultdict(list)
            for key in keys:
                a, b = eligible[start][key], eligible[end][key]
                af, ag, bf, bg = [
                    Decimal(x)
                    for x in [
                        a["fuel_mmbtu"],
                        a["net_mwh"],
                        b["fuel_mmbtu"],
                        b["net_mwh"],
                    ]
                ]
                ha, hb = af / ag, bf / bg
                wa, wb = ag / g0, bg / g1
                r = contrib_by[cid][key]
                c.exact(r["plant"], a["plant"], "contribution plant")
                for field, want in [
                    ("fuel0", af),
                    ("generation0", ag),
                    ("fuel1", bf),
                    ("generation1", bg),
                ]:
                    c.exact(Decimal(r[field]), want, field)
                terms = dict(
                    h0=ha,
                    h1=hb,
                    s0=wa,
                    s1=wb,
                    within=(wa + wb) * (hb - ha) / 2,
                    mix=(ha + hb) * (wb - wa) / 2,
                    within_initial_shares=wa * (hb - ha),
                    mix_final_ratios=hb * (wb - wa),
                    within_final_shares=wb * (hb - ha),
                    mix_initial_ratios=ha * (wb - wa),
                )
                for field, want in terms.items():
                    c.numeric(r[field], want, "contribution " + field)
                for field in [
                    "within",
                    "mix",
                    "within_initial_shares",
                    "mix_final_ratios",
                    "within_final_shares",
                    "mix_initial_ratios",
                ]:
                    sums[field] += terms[field]
                native[key] = (af, ag, bf, bg)
                byplant[a["plant"]].append(key)
            expected = dict(
                matched_heat_rate0=hm0,
                matched_heat_rate1=hm1,
                full_heat_rate0=h0full,
                full_heat_rate1=h1full,
                matched_change=hm1 - hm0,
                full_change=h1full - h0full,
                outside_cohort_composition_remainder=(h1full - hm1) - (h0full - hm0),
                generation_coverage0=g0 / totals[start][1],
                generation_coverage1=g1 / totals[end][1],
                **sums,
                identity_residual=ZERO,
                bridge_residual=ZERO,
            )
            for field, want in expected.items():
                c.numeric(result[field], want, "case " + field)
            c.numeric(
                sums["within_initial_shares"] + sums["mix_final_ratios"],
                hm1 - hm0,
                "independent first path identity",
            )
            c.numeric(
                sums["within_final_shares"] + sums["mix_initial_ratios"],
                hm1 - hm0,
                "independent second path identity",
            )
            c.numeric(
                sums["within"],
                (sums["within_initial_shares"] + sums["within_final_shares"]) / 2,
                "independent path average",
            )
            if grain != "plant_fuel" or cohort != "pair_common":
                c.exact(len(influence_by[cid]), 0, "no undeclared influence expansion")
                continue
            c.exact(set(influence_by[cid]), set(plants), "all primary plant deletions")
            # Reconstruct sufficient sums from independently verified native cells.
            total_a = sum((ag * (bf / bg) for af, ag, bf, bg in native.values()), ZERO)
            total_b = sum((bg * (af / ag) for af, ag, bf, bg in native.values()), ZERO)
            chosen = set([plants[0], plants[len(plants) // 2], plants[-1]])
            for plant in plants:
                rr = influence_by[cid][plant]
                removed = [native[k] for k in byplant[plant]]
                rf0, rg0, rf1, rg1 = [
                    sum((r[j] for r in removed), ZERO) for j in range(4)
                ]
                ff0, gg0, ff1, gg1 = f0 - rf0, g0 - rg0, f1 - rf1, g1 - rg1
                aa = total_a - sum((ag * (bf / bg) for af, ag, bf, bg in removed), ZERO)
                bb = total_b - sum((bg * (af / ag) for af, ag, bf, bg in removed), ZERO)
                within = (aa / gg0 - ff0 / gg0 + ff1 / gg1 - bb / gg1) / 2
                delta = ff1 / gg1 - ff0 / gg0
                mix = delta - within
                c.exact(rr["state"], "ESTIMABLE", "deletion availability")
                c.exact(
                    int(rr["remaining_plants"]), len(plants) - 1, "remaining plants"
                )
                c.exact(
                    int(rr["remaining_cells"]),
                    len(keys) - len(removed),
                    "remaining cells",
                )
                for field, want in [
                    ("within", within),
                    ("mix", mix),
                    ("matched_change", delta),
                    ("identity_residual", ZERO),
                ]:
                    c.numeric(rr[field], want, "plant deletion " + field)
                all_influence += 1
                if plant in chosen:
                    direct_w = direct_m = ZERO
                    for key in keys:
                        if key in byplant[plant]:
                            continue
                        af, ag, bf, bg = native[key]
                        ha, hb = af / ag, bf / bg
                        wa, wb = ag / gg0, bg / gg1
                        direct_w += (wa + wb) * (hb - ha) / 2
                        direct_m += (ha + hb) * (wb - wa) / 2
                    c.numeric(rr["within"], direct_w, "direct deletion within")
                    c.numeric(rr["mix"], direct_m, "direct deletion mix")
                    direct_checks += 1
        ranges = json.loads((out / "influence_ranges.json").read_bytes())
        c.exact(len(ranges), 9, "primary influence-range count")
        for r in ranges:
            rows = list(influence_by[r["case_id"]].values())
            valid = [v for v in rows if v["state"] == "ESTIMABLE"]
            c.exact(r["deletions"], len(rows), "range deletions")
            c.exact(r["estimable_deletions"], len(valid), "range availability")
            for field in ["within", "mix", "matched_change"]:
                values = [Decimal(v[field]) for v in valid]
                c.exact(
                    Decimal(r["ranges"][field]["minimum"]),
                    min(values),
                    "finite range minimum",
                )
                c.exact(
                    Decimal(r["ranges"][field]["maximum"]),
                    max(values),
                    "finite range maximum",
                )
    summary = json.loads((out / "summary.json").read_bytes())
    c.exact(summary["cases"], 36, "summary cases")
    c.exact(summary["cell_contributions"], len(contributions), "summary contributions")
    c.exact(summary["plant_deletions"], len(influence), "summary deletions")
    c.exact(summary["new_selection_made"], False, "no selection")
    c.exact(
        summary["original_v1_gate"], "FAILED_UNCHANGED", "preserved original failure"
    )
    c.exact(
        summary["primary_cases"],
        [
            r
            for r in results
            if r["grain"] == "plant_fuel" and r["cohort"] == "pair_common"
        ],
        "primary summary matches complete cases",
    )
    c.exact(
        summary["estimable_cases"],
        sum(r["state"] == "ESTIMABLE" for r in results),
        "estimable case count",
    )
    result = dict(
        status="PASS_INDEPENDENT_V2_DECOMPOSITIONS",
        phase=phase,
        conditions=c.conditions,
        cases=len(results),
        cell_contributions=len(contributions),
        plant_deletions=all_influence,
        direct_deletion_recomputations=direct_checks,
        maximum_absolute_numeric_difference=str(c.maximum),
        declared_absolute_tolerance="1e-45",
        independent_precision_digits=80,
        method="Independent source SQL/Decimal qualification; direct 80-digit per-cell paths, symmetry and outside-cohort bridge; separately reconstructed all-plant subtraction sums plus fixed first/middle/last direct deletions. No production aggregation/decomposition helpers imported.",
        original_v1_gate="FAILED_UNCHANGED",
    )
    (out / "independent_verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["development", "held"], required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    check(a.phase, a.out)
