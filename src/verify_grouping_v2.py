"""Independent SQLite/Decimal source grouping and complete membership lattice."""

import argparse, csv, gzip, io, json, sqlite3
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def numeric(text):
    try:
        n = Decimal(text)
    except InvalidOperation:
        return None
    return text if n.is_finite() else None


class Sum:
    def __init__(self):
        self.total = Decimal(0)

    def step(self, value):
        if value is not None:
            with localcontext() as c:
                c.prec = 80
                self.total += Decimal(value)

    def finalize(self):
        return str(self.total)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads((ROOT / "protocol_v2.json").read_bytes())
    db = sqlite3.connect(":memory:")
    db.create_aggregate("DEC_SUM", 1, Sum)
    db.execute(
        "CREATE TABLE source(year INT,source_row INT,plant TEXT,chp TEXT,state TEXT,pm TEXT,family TEXT,tech TEXT,f TEXT,g TEXT,negativef INT,negativeg INT,PRIMARY KEY(year,source_row))"
    )
    with gzip.open(
        ROOT / "data/v2/source_cells.csv.gz", "rt", encoding="utf-8", newline=""
    ) as f:
        source = list(csv.DictReader(f))
    for r in source:
        family = (
            "coal"
            if r["fuel"] in cfg["coal_codes"]
            else (
                "natural_gas" if r["fuel"] in cfg["natural_gas_codes"] else "diagnostic"
            )
        )
        tech = "CC" if r["prime_mover"] in ["CA", "CT", "CS"] else r["prime_mover"]
        f, g = numeric(r["elec_mmbtu_raw"]), numeric(r["net_mwh_raw"])
        db.execute(
            "INSERT INTO source VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(r["year"]),
                int(r["source_row"]),
                r["plant"],
                r["chp"],
                r["state"],
                r["prime_mover"],
                family,
                tech,
                f,
                g,
                int(f is not None and Decimal(f) < 0),
                int(g is not None and Decimal(g) < 0),
            ),
        )
    states = ",".join("?" for _ in cfg["states"])
    where = "family!='diagnostic' AND chp='N' AND state IN (" + states + ")"
    expected = {}
    conditions = 0
    for grain in ["plant_fuel", "plant_technology_fuel"]:
        tech = "''" if grain == "plant_fuel" else "tech"
        sql = f"""SELECT year,plant,{tech} AS technology,family,COUNT(*),DEC_SUM(f),DEC_SUM(g),SUM(f IS NULL),SUM(g IS NULL),SUM(negativef),SUM(negativeg),GROUP_CONCAT(source_row) FROM (SELECT * FROM source ORDER BY year,source_row) WHERE {where} GROUP BY year,plant,technology,family"""
        for (
            year,
            plant,
            technology,
            family,
            n,
            f,
            g,
            mf,
            mg,
            nf,
            ng,
            locators,
        ) in db.execute(sql, cfg["states"]):
            key = "|".join(
                [plant, family]
                if grain == "plant_fuel"
                else [plant, technology, family]
            )
            reason = (
                "missing_or_malformed_component"
                if mf or mg
                else (
                    "nonpositive_aggregate_fuel_or_generation"
                    if Decimal(f) <= 0 or Decimal(g) <= 0
                    else "eligible"
                )
            )
            expected[grain, year, key] = dict(
                grain=grain,
                year=year,
                key=key,
                plant=plant,
                technology=technology,
                fuel_group=family,
                source_components=n,
                source_rows=[int(v) for v in locators.split(",")],
                missing_fuel_components=mf,
                missing_generation_components=mg,
                negative_fuel_components=nf,
                negative_generation_components=ng,
                fuel_mmbtu=None if mf else f,
                net_mwh=None if mg else g,
                known_fuel_component_sum=f,
                known_generation_component_sum=g,
                eligible=reason == "eligible",
                reason=reason,
            )
    ledger = json.loads(gzip.decompress((a.out / "group_ledger.json.gz").read_bytes()))
    actual = {(r["grain"], r["year"], r["key"]): r for r in ledger}
    assert len(actual) == len(ledger) and set(actual) == set(expected)
    for key, row in expected.items():
        stored = actual[key]
        assert set(stored) == set(row)
        for field, value in row.items():
            if (
                field
                in [
                    "fuel_mmbtu",
                    "net_mwh",
                    "known_fuel_component_sum",
                    "known_generation_component_sum",
                ]
                and value is not None
            ):
                assert Decimal(stored[field]) == Decimal(value)
            else:
                assert stored[field] == value, (key, field, stored[field], value)
            conditions += 1
    excluded = json.loads((a.out / "excluded_source_rows.json").read_bytes())
    ex = []
    sql = f"""SELECT year,CASE WHEN family='diagnostic' THEN 'diagnostic_waste_heat' WHEN chp!='N' THEN 'not_explicit_non_chp' ELSE 'outside_50_states_dc' END AS reason,COUNT(*),DEC_SUM(f),DEC_SUM(g),SUM(f IS NULL),SUM(g IS NULL) FROM source WHERE NOT ({where}) GROUP BY year,reason ORDER BY year,reason"""
    for year, reason, n, f, g, mf, mg in db.execute(sql, cfg["states"]):
        ex.append(
            dict(
                year=year,
                reason=reason,
                rows=n,
                known_fuel_mmbtu=f,
                known_net_mwh=g,
                missing_fuel_values=mf,
                missing_generation_values=mg,
            )
        )
    assert len(excluded) == len(ex)
    for stored, want in zip(excluded, ex):
        for field, value in want.items():
            if field in ["known_fuel_mmbtu", "known_net_mwh"]:
                assert Decimal(stored[field]) == Decimal(value)
            else:
                assert stored[field] == value
            conditions += 1
    support = json.loads((a.out / "case_support.json").read_bytes())
    assert len(support) == 72
    seen = set()
    for row in support:
        identity = row["end_year"], row["fleet"], row["grain"], row["cohort"]
        assert identity not in seen
        seen.add(identity)
        eligible = {
            year: {
                key[2]: value
                for key, value in expected.items()
                if key[0] == row["grain"]
                and key[1] == year
                and value["eligible"]
                and (row["fleet"] == "pooled" or value["fuel_group"] == row["fleet"])
            }
            for year in cfg["years"]
        }
        years = (
            [row["end_year"] - 1, row["end_year"]]
            if row["cohort"] == "pair_common"
            else cfg["years"]
        )
        common = set.intersection(*(set(eligible[y]) for y in years))
        plants = {eligible[row["end_year"]][k]["plant"] for k in common}
        primary = row["grain"] == "plant_fuel" and row["cohort"] == "pair_common"
        for field, want in [
            ("matched_cells", len(common)),
            ("matched_plants", len(plants)),
            ("required_primary_support", primary),
            ("primary_support_pass", not primary or len(plants) >= 2),
        ]:
            assert row[field] == want
            conditions += 1
    summary = json.loads((a.out / "qualification.json").read_bytes())
    counts = Counter((r["grain"], r["year"], r["reason"]) for r in expected.values())
    assert summary["group_counts"] == [
        dict(grain=g, year=y, reason=r, cells=n)
        for (g, y, r), n in sorted(counts.items())
    ]
    assert summary["decomposition_outcomes_computed"] is False
    result = dict(
        status="PASS_INDEPENDENT_SQL_DECIMAL_GROUPING_AND_SUPPORT",
        source_rows=len(source),
        group_rows=len(expected),
        case_support_rows=72,
        conditions=conditions,
        primary_support_failures=sum(not r["primary_support_pass"] for r in support),
        method="Separate SQLite CASE/grouping, 80-digit Decimal aggregate, independent eligibility and set intersections; no production grouping/decomposition helpers imported",
        original_v1_gate="FAILED_UNCHANGED",
        decomposition_outcomes_computed=False,
    )
    (a.out / "independent_grouping_verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
