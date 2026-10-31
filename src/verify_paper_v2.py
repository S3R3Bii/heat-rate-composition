"""Verify exact source bindings and the reviewed manuscript's scientific qualifications."""

import ast, hashlib, json
from decimal import Decimal, localcontext
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
read = lambda n: json.loads((ROOT / n).read_bytes())


def main():
    tex = (ROOT / "paper/main.tex").read_text(encoding="utf-8")
    pdf = PdfReader(ROOT / "paper/manuscript.pdf")
    assert len(pdf.pages) == 6
    pages = [p.extract_text() or "" for p in pdf.pages]
    assert all(p.strip() for p in pages)
    flat = "\n".join(pages)
    bindings = read("paper_bindings_v2.json")
    checks = 0
    with localcontext() as context:
        context.prec = 100
        for name, item in bindings.items():
            path = (ROOT / item["file"]).resolve()
            assert path.is_relative_to(ROOT) and path.suffix == ".json"
            value = json.loads(path.read_bytes())
            for key in item["pointer"]:
                value = value[key]
            assert item["value"] == value
            checks += 1
            fmt = item["format"]
            assert fmt in ["integer", "six", "percent", "scientific"]
            display = (
                f"{value:,}"
                if fmt == "integer"
                else (
                    format(Decimal(value), ".6f")
                    if fmt == "six"
                    else (
                        format(Decimal(value) * 100, ".3f")
                        if fmt == "percent"
                        else format(Decimal(value), ".2E")
                    )
                )
            )
            assert item["display"] == display
            checks += 1
            assert (
                "\\newcommand{\\" + name + "}{" + display + "}" in tex
                and "\\" + name + "{}" in tex
            )
            checks += 1
            assert display in flat, (name, display)
            checks += 1
    assert len(bindings) == 43
    checks += 1
    original = read("results/SOURCE_FAILURE.json")
    assert (
        original["released"] is False
        and original["analysis_started"] is False
        and original["source_gate"].startswith("FAIL")
    )
    checks += 1
    native = read("data/v2/independent_source_verification.json")
    assert (
        native["retained_rows"] == 27842
        and native["quarantined_plants"] == 18
        and native["quarantined_selected_rows"] == 736
        and native["ambiguous_quantities_aggregated"] is False
    )
    checks += 1
    qualification = read("data/v2/qualification.json")
    assert (
        qualification["group_rows"] == 29996
        and qualification["primary_support_cases"] == 18
        and not qualification["failed_primary_support_cases"]
        and qualification["empty_secondary_cases"] == 0
    )
    checks += 1
    dev, held = [read(f"results/v2/{p}/cases.json") for p in ["development", "held"]]
    assert len(dev) == len(held) == 36 and all(
        r["state"] == "ESTIMABLE" for r in dev + held
    )
    checks += 1
    latest = next(
        r
        for r in held
        if r["end_year"] == 2024
        and r["fleet"] == "pooled"
        and r["grain"] == "plant_fuel"
        and r["cohort"] == "pair_common"
    )
    assert (
        Decimal(latest["within"]) < 0 < Decimal(latest["mix"])
        and Decimal(latest["full_change"]) < 0
    )
    checks += 1
    assert read("data/v2/frozen_dependencies.json")["dependency_count"] == 37
    checks += 1
    for phase, conditions, cells, deletions in [
        ("development", 658242, 36476, 9158),
        ("held", 682050, 37636, 9814),
    ]:
        proof = read(f"results/v2/{phase}/independent_verification.json")
        assert (
            proof["status"] == "PASS_INDEPENDENT_V2_DECOMPOSITIONS"
            and proof["conditions"] == conditions
            and proof["cell_contributions"] == cells
            and proof["plant_deletions"] == deletions
            and proof["direct_deletion_recomputations"] == 27
        )
        checks += 1
    methods = sum(
        isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        for p in (ROOT / "tests").glob("test_*.py")
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
    )
    assert methods == 22
    checks += 1
    for suffix, version in [("310", "3.10.11"), ("312", "3.12.14")]:
        proof = read(f"results/v2/reproduction_cpython{suffix}.json")
        assert (
            proof["status"] == "PASS_ANALYSIS_ONLY_REPLAY"
            and proof["python"] == version
            and proof["exact_fields"] == 615290
            and proof["numeric_fields"] == 818646
            and proof["source_files_unchanged"] == 3
            and proof["source_requests"] == 0
        )
        checks += 1
    for phrase in [
        "Not peer reviewed",
        "Ambiguous quantities are not combined",
        "not the complete national fleet",
        "The original failure remains unchanged",
        "not a blinded collection or external preregistration",
        "negative source components are retained",
        "undefined unmatched ratios are never filled with zero",
        "not a physical plant entry/retirement measure",
        "not a new causal attribution method",
        "Balanced membership uses future eligibility",
        "not a confidence interval",
        "not additional independent source observations",
        "No fitting, tuning, machine learning",
        "not EIA measurement accuracy",
        "not a production-speed benchmark",
    ]:
        assert phrase in tex, phrase
        checks += 1
    build = read("paper/build_receipt.json")
    assert (
        build["status"] == "PASS_COMPILE_AND_SIX_PAGE_VISUAL_REVIEW"
        and build["pages"] == 6
        and not build["layout_warnings"]
    )
    checks += 1
    for path, digest in build["artifact_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        checks += 1
    for p in (ROOT / "paper/images").glob("*.pdf"):
        assert p.read_bytes() == (ROOT / "figures" / p.name).read_bytes()
        checks += 1
    result = dict(
        status="PASS_SOURCE_BOUND_V2_MANUSCRIPT",
        pages=6,
        bound_values=len(bindings),
        conditions=checks,
        manuscript_sha256=hashlib.sha256(
            (ROOT / "paper/manuscript.pdf").read_bytes()
        ).hexdigest(),
        page_characters=[len(p) for p in pages],
        original_failure_quarantine_and_reported_not_engineering_scope_explicit=True,
        rendering="Six current Poppler renders individually inspected; CI checks source bindings and reviewed artifact hashes without compiling TeX.",
    )
    (ROOT / "paper_verification_v2.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
