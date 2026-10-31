"""Apply the fixed identity-only quarantine before projecting unambiguous source facts."""

import argparse, csv, gzip, hashlib, io, json, zipfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ingest import workbook_rows

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "year",
    "plant",
    "chp",
    "state",
    "prime_mover",
    "fuel",
    "nuclear_unit",
    "elec_mmbtu",
    "net_mwh",
]
PUBLIC_FIELDS = [
    "year",
    "source_row",
    "plant",
    "chp",
    "state",
    "prime_mover",
    "fuel",
    "nuclear_unit",
    "elec_mmbtu_raw",
    "net_mwh_raw",
    "fuel_xml_type",
    "generation_xml_type",
    "selected_fields_sha256",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def scan(originals):
    cfg = json.loads((ROOT / "protocol_v2.json").read_bytes())
    archives = json.loads((ROOT / "data/source/archives.json").read_bytes())
    selected = set(
        cfg["coal_codes"] + cfg["natural_gas_codes"] + cfg["diagnostic_fuels"]
    )
    contexts = defaultdict(lambda: defaultdict(list))
    keys = defaultdict(list)
    counts = Counter()
    meta = []
    for arc in archives:
        raw = (originals / f"f923_{arc['year']}.zip").read_bytes()
        assert len(raw) == arc["bytes"] and digest(raw) == arc["sha256"]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            book = z.read(arc["selected_member"])
        columns = None
        yearcounts = Counter()
        for rownum, cells in workbook_rows(book, cfg["source_sheet"]):
            if rownum == cfg["source_header_row"]:
                columns = {}
                for name, label in cfg["source_fields"].items():
                    matched = [
                        col for col, (value, kind) in cells.items() if value == label
                    ]
                    assert len(matched) == 1, (arc["year"], name)
                    columns[name] = matched[0]
                continue
            if rownum <= cfg["source_header_row"]:
                continue
            yearcounts["native_xml_rows"] += 1
            fuel = cells.get(columns["fuel"], ("", ""))[0]
            rawplant = cells.get(columns["plant"], ("", ""))[0]
            rawyear = cells.get(columns["year"], ("", ""))[0]
            try:
                plant = Decimal(rawplant)
                year = Decimal(rawyear)
            except InvalidOperation:
                assert fuel not in selected, "Malformed required source identity"
                yearcounts["unkeyed_nonselected_rows"] += 1
                continue
            assert plant.is_finite() and year.is_finite()
            if plant <= 0 or plant != plant.to_integral_value() or year != arc["year"]:
                assert fuel not in selected, "Malformed required source identity"
                yearcounts["unkeyed_nonselected_rows"] += 1
                continue
            plant = str(int(plant))
            yearcounts["valid_identity_rows"] += 1
            state = cells.get(columns["state"], ("", ""))[0]
            chp = cells.get(columns["chp"], ("", ""))[0]
            contexts[int(year), plant][state, chp].append(rownum)
            if fuel in selected:
                pm = cells.get(columns["prime_mover"], ("", ""))[0]
                assert pm in cfg["allowed_prime_movers"], (
                    "Unknown selected prime mover",
                    pm,
                )
                keys[int(year), plant, pm, fuel].append(rownum)
                yearcounts["selected_fuel_rows_before_quarantine"] += 1
        assert columns is not None
        meta.append(
            dict(
                year=arc["year"],
                archive_sha256=arc["sha256"],
                workbook_sha256=digest(book),
                selected_member=arc["selected_member"],
                columns=columns,
                identity_counts=dict(yearcounts),
            )
        )
    quarantine = set()
    events = []
    for (year, plant), mapping in sorted(contexts.items()):
        if len(mapping) > 1:
            quarantine.add(plant)
            events.append(
                dict(
                    plant=plant,
                    year=year,
                    reason="conflicting_plant_year_state_or_chp",
                    contexts=[
                        dict(state=s, chp=c, source_rows=rows)
                        for (s, c), rows in sorted(mapping.items())
                    ],
                )
            )
    for (year, plant, pm, fuel), rows in sorted(keys.items()):
        if len(rows) > 1:
            quarantine.add(plant)
            events.append(
                dict(
                    plant=plant,
                    year=year,
                    reason="duplicate_selected_key",
                    prime_mover=pm,
                    fuel=fuel,
                    source_rows=rows,
                )
            )
    return cfg, archives, meta, quarantine, events, contexts, keys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--originals", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Fresh source output required; retain earlier evidence")
    a.out.mkdir(parents=True)
    cfg, archives, meta, quarantine, events, contexts, keys = scan(a.originals)
    # Only identity/classification rules above decide quarantine membership.
    selected = set(
        cfg["coal_codes"] + cfg["natural_gas_codes"] + cfg["diagnostic_fuels"]
    )
    records = []
    count = Counter()
    excluded = Counter()
    quantities_not_aggregated = Counter()
    for arc, m in zip(archives, meta):
        with zipfile.ZipFile(a.originals / f"f923_{arc['year']}.zip") as z:
            book = z.read(arc["selected_member"])
        for rownum, cells in workbook_rows(book, cfg["source_sheet"]):
            if rownum <= cfg["source_header_row"]:
                continue
            columns = m["columns"]
            fuel = cells.get(columns["fuel"], ("", ""))[0]
            if fuel not in selected:
                continue
            raw = [cells.get(columns[name], ("", ""))[0] for name in FIELDS]
            year, plant, chp, state, pm, fuel, nuclear, f, g = raw
            plant = str(int(Decimal(plant)))
            if plant in quarantine:
                excluded[arc["year"], plant] += 1
                quantities_not_aggregated[arc["year"]] += 1
                continue
            assert (
                len(contexts[arc["year"], plant]) == 1
                and len(keys[arc["year"], plant, pm, fuel]) == 1
            )
            records.append(
                [
                    arc["year"],
                    rownum,
                    plant,
                    chp,
                    state,
                    pm,
                    fuel,
                    nuclear,
                    f,
                    g,
                    cells.get(columns["elec_mmbtu"], ("", ""))[1],
                    cells.get(columns["net_mwh"], ("", ""))[1],
                    digest("\x1f".join(raw).encode()),
                ]
            )
            count[arc["year"], fuel] += 1
    stream = io.StringIO(newline="")
    w = csv.writer(stream, lineterminator="\n")
    w.writerow(PUBLIC_FIELDS)
    w.writerows(records)
    packed = io.BytesIO()
    with gzip.GzipFile(
        fileobj=packed, filename="", mode="wb", mtime=0, compresslevel=9
    ) as f:
        f.write(stream.getvalue().encode())
    (a.out / "source_cells.csv.gz").write_bytes(packed.getvalue())
    manifest = dict(
        status="V2_PROJECTION_PENDING_INDEPENDENT_NATIVE_CHECK",
        source="EIA-923 final historical annual workbooks, exact retained2018–2024 archives",
        years=meta,
        quarantined_plants=sorted(quarantine, key=int),
        quarantined_plant_count=len(quarantine),
        quarantine_events=events,
        quarantined_selected_rows_by_year=[
            dict(year=y, rows=n) for y, n in sorted(quantities_not_aggregated.items())
        ],
        retained_rows=len(records),
        retained_rows_by_year_fuel=[
            dict(year=y, fuel=f, rows=n) for (y, f), n in sorted(count.items())
        ],
        source_cells_sha256=digest(packed.getvalue()),
        original_v1_gate="FAILED_UNCHANGED",
        quantities_for_ambiguous_rows_aggregated=False,
        decomposition_outcomes_computed=False,
        scope="Only unambiguous source identities; subsequent explicit non-CHP/state/fuel/completeness/aggregate-positivity rules remain mandatory. Not the complete national fleet or a known share of national output.",
        units=dict(
            elec_mmbtu_raw="Electricity fuel consumption, MMBtu",
            net_mwh_raw="Net generation, MWh",
        ),
        omitted="Raw workbooks; other sheets; plant/operator/contact names; coordinates; private cost fields; ambiguous quantities; agency artwork",
    )
    (a.out / "source_manifest.json").write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            dict(
                status=manifest["status"],
                source_rows_retained=len(records),
                quarantined_plants=len(quarantine),
                quarantine_events=len(events),
                ambiguous_rows=sum(quantities_not_aggregated.values()),
                decomposition_outcomes_computed=False,
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
