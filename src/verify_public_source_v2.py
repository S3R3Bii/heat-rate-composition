"""Check public source identities/hashes and retain the original native certificate boundary."""

import csv, gzip, hashlib, io, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
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
        hashlib.sha256((folder / "source_manifest.json").read_bytes()).hexdigest()
        == native["public_manifest_sha256"]
    )
    assert native["status"] == "PASS_INDEPENDENT_V2_NATIVE_SOURCE"
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))
    keys = set()
    contexts = {}
    locators = set()
    counts = Counter()
    quarantine = set(manifest["quarantined_plants"])
    for r in rows:
        y = int(r["year"])
        key = y, r["plant"], r["prime_mover"], r["fuel"]
        locator = y, int(r["source_row"])
        assert (
            key not in keys and locator not in locators and r["plant"] not in quarantine
        )
        keys.add(key)
        locators.add(locator)
        context = r["state"], r["chp"]
        assert contexts.setdefault((y, r["plant"]), context) == context
        assert len(r["selected_fields_sha256"]) == 64 and all(
            c in "0123456789abcdef" for c in r["selected_fields_sha256"]
        )
        counts[y, r["fuel"]] += 1
    assert len(rows) == manifest["retained_rows"] == native["retained_rows"] == 27842
    assert manifest["retained_rows_by_year_fuel"] == [
        dict(year=y, fuel=f, rows=n) for (y, f), n in sorted(counts.items())
    ]
    assert (
        native["quarantined_selected_rows"]
        == sum(r["rows"] for r in manifest["quarantined_selected_rows_by_year"])
        == 736
    )
    assert (
        native["original_v1_gate"] == "FAILED_UNCHANGED"
        and not native["ambiguous_quantities_aggregated"]
    )
    print(
        json.dumps(
            dict(
                status="PASS_PUBLIC_V2_SOURCE_CONSISTENCY",
                retained_rows=len(rows),
                quarantined_plants=len(quarantine),
                source="Selected public facts plus exact original native-reader certificate; no reacquisition of private full workbooks",
                original_v1_gate="FAILED_UNCHANGED",
            )
        )
    )


if __name__ == "__main__":
    main()
