"""Exact source sums and fixed Decimal rate decomposition; no engineering attribution."""

import csv, gzip, hashlib, io, json, subprocess
from collections import defaultdict, Counter
from decimal import Decimal, InvalidOperation, Inexact, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO = Decimal(0)
TWO = Decimal(2)


def config():
    return json.loads((ROOT / "protocol_v2.json").read_bytes())


def number(text):
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def exact_sum(values):
    values = list(values)
    if not values:
        return ZERO
    precision = max(
        60,
        max(v.adjusted() for v in values)
        - min(v.as_tuple().exponent for v in values)
        + len(str(len(values)))
        + 3,
    )
    with localcontext() as context:
        context.prec = precision
        context.clear_flags()
        total = sum(values, ZERO)
        if context.flags[Inexact]:
            raise ArithmeticError("Source summation was not exact")
        return total


def load_source():
    folder = ROOT / "data/v2"
    manifest = json.loads((folder / "source_manifest.json").read_bytes())
    native = json.loads((folder / "independent_source_verification.json").read_bytes())
    raw = (folder / "source_cells.csv.gz").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == manifest["source_cells_sha256"]
        == native["public_source_sha256"]
    )
    assert (
        native["status"] == "PASS_INDEPENDENT_V2_NATIVE_SOURCE"
        and native["original_v1_gate"] == "FAILED_UNCHANGED"
    )
    assert (
        hashlib.sha256((folder / "source_manifest.json").read_bytes()).hexdigest()
        == native["public_manifest_sha256"]
    )
    return list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))


def cells_from_source(rows, cfg):
    grouped = defaultdict(list)
    excluded = defaultdict(list)
    for row in rows:
        year = int(row["year"])
        fuel = row["fuel"]
        family = (
            "coal"
            if fuel in cfg["coal_codes"]
            else "natural_gas" if fuel in cfg["natural_gas_codes"] else None
        )
        reason = (
            "diagnostic_waste_heat"
            if family is None
            else (
                "not_explicit_non_chp"
                if row["chp"] != "N"
                else (
                    "outside_50_states_dc"
                    if row["state"] not in cfg["states"]
                    else None
                )
            )
        )
        if reason:
            excluded[year, reason].append(row)
            continue
        tech = (
            "CC"
            if row["prime_mover"] in cfg["combined_cycle_codes"]
            else row["prime_mover"]
        )
        for grain, key in [
            ("plant_fuel", (row["plant"], family)),
            ("plant_technology_fuel", (row["plant"], tech, family)),
        ]:
            grouped[grain, year, key].append(row)
    cells = {grain: {year: {} for year in cfg["years"]} for grain in cfg["grain"]}
    ledger = []
    for (grain, year, key), rr in sorted(grouped.items()):
        ff = [number(r["elec_mmbtu_raw"]) for r in rr]
        gg = [number(r["net_mwh_raw"]) for r in rr]
        knownf = exact_sum(v for v in ff if v is not None)
        knowng = exact_sum(v for v in gg if v is not None)
        missingf = sum(v is None for v in ff)
        missingg = sum(v is None for v in gg)
        f = None if missingf else knownf
        g = None if missingg else knowng
        reason = (
            "missing_or_malformed_component"
            if f is None or g is None
            else (
                "nonpositive_aggregate_fuel_or_generation"
                if f <= 0 or g <= 0
                else "eligible"
            )
        )
        fact = dict(
            grain=grain,
            year=year,
            key="|".join(key),
            plant=key[0],
            technology="" if grain == "plant_fuel" else key[1],
            fuel_group=key[-1],
            source_components=len(rr),
            source_rows=[int(r["source_row"]) for r in rr],
            missing_fuel_components=missingf,
            missing_generation_components=missingg,
            negative_fuel_components=sum(v is not None and v < 0 for v in ff),
            negative_generation_components=sum(v is not None and v < 0 for v in gg),
            fuel_mmbtu=None if f is None else str(f),
            net_mwh=None if g is None else str(g),
            known_fuel_component_sum=str(knownf),
            known_generation_component_sum=str(knowng),
            eligible=reason == "eligible",
            reason=reason,
        )
        cells[grain][year]["|".join(key)] = fact
        ledger.append(fact)
    exclusions = []
    for (year, reason), rr in sorted(excluded.items()):
        ff = [number(r["elec_mmbtu_raw"]) for r in rr]
        gg = [number(r["net_mwh_raw"]) for r in rr]
        exclusions.append(
            dict(
                year=year,
                reason=reason,
                rows=len(rr),
                known_fuel_mmbtu=str(exact_sum(v for v in ff if v is not None)),
                known_net_mwh=str(exact_sum(v for v in gg if v is not None)),
                missing_fuel_values=sum(v is None for v in ff),
                missing_generation_values=sum(v is None for v in gg),
                meaning="As-reported unambiguous source-row sums; waste heat remains separate from selected fuel attribution.",
            )
        )
    return cells, ledger, exclusions


def eligible(cells, year, fleet):
    return {
        k: v
        for k, v in cells[year].items()
        if v["eligible"] and (fleet == "pooled" or v["fuel_group"] == fleet)
    }


def matching(cells, year0, year1, fleet, cohort, years):
    byyear = {y: eligible(cells, y, fleet) for y in years}
    keys = (
        set(byyear[year0]) & set(byyear[year1])
        if cohort == "pair_common"
        else set.intersection(*(set(byyear[y]) for y in years))
    )
    return byyear, sorted(keys)


def support_qualification(cells, cfg):
    rows = []
    for end in cfg["years"][1:]:
        for fleet in cfg["fleets"]:
            for grain in cfg["grain"]:
                for cohort in cfg["cohorts"]:
                    byyear, keys = matching(
                        cells[grain], end - 1, end, fleet, cohort, cfg["years"]
                    )
                    plants = len({byyear[end][k]["plant"] for k in keys})
                    primary = grain == "plant_fuel" and cohort == "pair_common"
                    rows.append(
                        dict(
                            end_year=end,
                            fleet=fleet,
                            grain=grain,
                            cohort=cohort,
                            matched_cells=len(keys),
                            matched_plants=plants,
                            required_primary_support=primary,
                            primary_support_pass=not primary
                            or plants >= cfg["primary_minimum_matched_plants"],
                        )
                    )
    assert len(rows) == 72
    return rows


def case(cells, cfg, end, fleet, grain, cohort):
    cid = f"{end-1}-{end}__{fleet}__{grain}__{cohort}"
    byyear, keys = matching(cells[grain], end - 1, end, fleet, cohort, cfg["years"])
    plants = sorted({byyear[end][k]["plant"] for k in keys}, key=int)
    base = dict(
        case_id=cid,
        start_year=end - 1,
        end_year=end,
        fleet=fleet,
        grain=grain,
        cohort=cohort,
        matched_cells=len(keys),
        matched_plants=len(plants),
    )
    if (
        not keys
        or grain == "plant_fuel"
        and cohort == "pair_common"
        and len(plants) < cfg["primary_minimum_matched_plants"]
    ):
        return (
            dict(
                base,
                state="NOT_ESTIMABLE",
                reason="empty_matched_cohort_or_fixed_primary_support",
            ),
            [],
            [],
        )
    with localcontext() as context:
        context.prec = cfg["precision_digits"]
        total = {
            y: {
                name: exact_sum(Decimal(v[field]) for v in byyear[y].values())
                for name, field in [("f", "fuel_mmbtu"), ("g", "net_mwh")]
            }
            for y in [end - 1, end]
        }
        matched = {
            y: {
                name: exact_sum(Decimal(byyear[y][k][field]) for k in keys)
                for name, field in [("f", "fuel_mmbtu"), ("g", "net_mwh")]
            }
            for y in [end - 1, end]
        }
        if any(total[y]["g"] <= 0 or matched[y]["g"] <= 0 for y in [end - 1, end]):
            return (
                dict(base, state="NOT_ESTIMABLE", reason="nonpositive_denominator"),
                [],
                [],
            )
        g0, g1 = matched[end - 1]["g"], matched[end]["g"]
        f0, f1 = matched[end - 1]["f"], matched[end]["f"]
        contributions = []
        influence_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
        for key in keys:
            a, b = byyear[end - 1][key], byyear[end][key]
            af, ag, bf, bg = [
                Decimal(v)
                for v in [a["fuel_mmbtu"], a["net_mwh"], b["fuel_mmbtu"], b["net_mwh"]]
            ]
            h0, h1 = af / ag, bf / bg
            s0, s1 = ag / g0, bg / g1
            dh, ds = h1 - h0, s1 - s0
            terms = dict(
                within=(s0 + s1) * dh / TWO,
                mix=(h0 + h1) * ds / TWO,
                within_initial_shares=s0 * dh,
                mix_final_ratios=h1 * ds,
                within_final_shares=s1 * dh,
                mix_initial_ratios=h0 * ds,
            )
            contributions.append(
                dict(
                    case_id=cid,
                    key=key,
                    plant=a["plant"],
                    fuel0=str(af),
                    generation0=str(ag),
                    fuel1=str(bf),
                    generation1=str(bg),
                    h0=str(h0),
                    h1=str(h1),
                    s0=str(s0),
                    s1=str(s1),
                    **{k: str(v) for k, v in terms.items()},
                )
            )
            p = influence_totals[a["plant"]]
            for name, value in [
                ("f0", af),
                ("g0", ag),
                ("f1", bf),
                ("g1", bg),
                ("cross0", ag * h1),
                ("cross1", bg * h0),
                ("cells", Decimal(1)),
            ]:
                p[name] += value
        sums = {
            name: sum((Decimal(r[name]) for r in contributions), ZERO)
            for name in [
                "within",
                "mix",
                "within_initial_shares",
                "mix_final_ratios",
                "within_final_shares",
                "mix_initial_ratios",
            ]
        }
        hfull0, hfull1 = (
            total[end - 1]["f"] / total[end - 1]["g"],
            total[end]["f"] / total[end]["g"],
        )
        hm0, hm1 = f0 / g0, f1 / g1
        change = hm1 - hm0
        remainder = (hfull1 - hm1) - (hfull0 - hm0)
        result = dict(
            base,
            state="ESTIMABLE",
            matched_fuel0=str(f0),
            matched_generation0=str(g0),
            matched_fuel1=str(f1),
            matched_generation1=str(g1),
            full_fuel0=str(total[end - 1]["f"]),
            full_generation0=str(total[end - 1]["g"]),
            full_fuel1=str(total[end]["f"]),
            full_generation1=str(total[end]["g"]),
            matched_heat_rate0=str(hm0),
            matched_heat_rate1=str(hm1),
            full_heat_rate0=str(hfull0),
            full_heat_rate1=str(hfull1),
            matched_change=str(change),
            full_change=str(hfull1 - hfull0),
            outside_cohort_composition_remainder=str(remainder),
            generation_coverage0=str(g0 / total[end - 1]["g"]),
            generation_coverage1=str(g1 / total[end]["g"]),
            **{k: str(v) for k, v in sums.items()},
            identity_residual=str(sums["within"] + sums["mix"] - change),
            bridge_residual=str(
                sums["within"] + sums["mix"] + remainder - (hfull1 - hfull0)
            ),
        )
        tolerance = Decimal(cfg["absolute_numeric_tolerance"])
        assert (
            abs(Decimal(result["identity_residual"])) <= tolerance
            and abs(Decimal(result["bridge_residual"])) <= tolerance
        )
        influence = []
        if grain == "plant_fuel" and cohort == "pair_common":
            sums_p = {
                name: sum((p[name] for p in influence_totals.values()), ZERO)
                for name in ["f0", "g0", "f1", "g1", "cross0", "cross1"]
            }
            for plant in plants:
                p = influence_totals[plant]
                v = {name: sums_p[name] - p[name] for name in sums_p}
                if v["g0"] <= 0 or v["g1"] <= 0:
                    influence.append(
                        dict(
                            case_id=cid,
                            removed_plant=plant,
                            state="NOT_ESTIMABLE",
                            reason="nonpositive_remaining_denominator",
                        )
                    )
                    continue
                within = (
                    (v["cross0"] - v["f0"]) / v["g0"]
                    + (v["f1"] - v["cross1"]) / v["g1"]
                ) / TWO
                mix = (
                    (v["f1"] + v["cross1"]) / v["g1"]
                    - (v["cross0"] + v["f0"]) / v["g0"]
                ) / TWO
                delta = v["f1"] / v["g1"] - v["f0"] / v["g0"]
                assert abs(within + mix - delta) <= tolerance
                influence.append(
                    dict(
                        case_id=cid,
                        removed_plant=plant,
                        state="ESTIMABLE",
                        remaining_plants=len(plants) - 1,
                        remaining_cells=len(keys) - int(p["cells"]),
                        within=str(within),
                        mix=str(mix),
                        matched_change=str(delta),
                        identity_residual=str(within + mix - delta),
                    )
                )
        return result, contributions, influence


def check_freeze():
    path = ROOT / "data/v2/frozen_dependencies.json"
    if not path.exists():
        raise ValueError("Committed v2 freeze required before held decomposition")
    frozen = json.loads(path.read_bytes())
    assert (
        subprocess.check_output(
            ["git", "show", "HEAD:data/v2/frozen_dependencies.json"], cwd=ROOT
        )
        == path.read_bytes()
    )
    for name, digest in frozen["dependencies"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
        assert (
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", frozen["development_commit"] + ":" + name], cwd=ROOT
                )
            ).hexdigest()
            == digest
        ), name
    return frozen
