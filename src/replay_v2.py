"""Replay the fixed Decimal decomposition from selected public source facts."""

import argparse, csv, gzip, hashlib, json, platform, subprocess, sys
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMERIC = {
    "h0",
    "h1",
    "s0",
    "s1",
    "within",
    "mix",
    "within_initial_shares",
    "mix_final_ratios",
    "within_final_shares",
    "mix_initial_ratios",
    "matched_heat_rate0",
    "matched_heat_rate1",
    "full_heat_rate0",
    "full_heat_rate1",
    "matched_change",
    "full_change",
    "outside_cohort_composition_remainder",
    "generation_coverage0",
    "generation_coverage1",
    "identity_residual",
    "bridge_residual",
    "minimum",
    "maximum",
}
QUANTITIES = {
    "fuel0",
    "generation0",
    "fuel1",
    "generation1",
    "matched_fuel0",
    "matched_generation0",
    "matched_fuel1",
    "matched_generation1",
    "full_fuel0",
    "full_generation0",
    "full_fuel1",
    "full_generation1",
}


class Comparison:
    def __init__(self):
        self.exact = 0
        self.numeric = 0
        self.maximum = Decimal(0)
        self.as_run = 0

    def value(self, a, b, path=""):
        if isinstance(a, dict):
            assert set(a) == set(b), path
            for key in a:
                if key == "maximum_absolute_numeric_difference":
                    assert Decimal(b[key]).is_finite() and 0 <= Decimal(
                        b[key]
                    ) <= Decimal("1e-45")
                    self.as_run += 1
                else:
                    self.value(a[key], b[key], path + "/" + key)
        elif isinstance(a, list):
            assert len(a) == len(b), path
            for x, y in zip(a, b):
                self.value(x, y, path)
        elif path.rsplit("/", 1)[-1] in NUMERIC and a is not None:
            aa, bb = Decimal(a), Decimal(b)
            assert aa.is_finite() and bb.is_finite()
            difference = abs(aa - bb)
            assert difference <= Decimal("1e-45"), (path, a, b)
            self.maximum = max(self.maximum, difference / Decimal("1e-45"))
            self.numeric += 1
        elif path.rsplit("/", 1)[-1] in QUANTITIES and a is not None:
            assert Decimal(a) == Decimal(b), (path, a, b)
            self.exact += 1
        else:
            assert a == b, (path, a, b)
            self.exact += 1

    def file(self, a, b):
        if a.name.endswith(".csv.gz"):
            with gzip.open(a, "rt", encoding="utf-8", newline="") as f:
                left = list(csv.DictReader(f))
            with gzip.open(b, "rt", encoding="utf-8", newline="") as f:
                right = list(csv.DictReader(f))
            assert len(left) == len(right)
            for x, y in zip(left, right):
                self.value(x, y, a.name)
        else:
            self.value(json.loads(a.read_bytes()), json.loads(b.read_bytes()), a.name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--analysis-only", action="store_true")
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Fresh external replay output required")
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT, text=True
        ).strip()
        == "false"
    )
    a.out.mkdir(parents=True)

    def run(name, *args):
        subprocess.run(
            [sys.executable, str(ROOT / "src" / name), *map(str, args)],
            cwd=ROOT,
            check=True,
        )

    sources = {
        n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
        for n in [
            "data/v2/source_cells.csv.gz",
            "data/v2/source_manifest.json",
            "data/v2/group_ledger.json.gz",
        ]
    }
    run("verify_public_source_v2.py")
    comparison = Comparison()
    proofs = {}
    with localcontext() as context:
        context.prec = 100
        for phase in ["development", "held"]:
            output = a.out / phase
            run("analyze_v2.py", "--phase", phase, "--out", output)
            run("verify_results_v2.py", "--phase", phase, "--out", output)
            for source in (ROOT / "results/v2" / phase).iterdir():
                if source.name != "runtime.json":
                    comparison.file(source, output / source.name)
            proofs[phase] = json.loads(
                (output / "independent_verification.json").read_bytes()
            )["conditions"]
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        check=True,
    )
    run("check_exercise_v2.py")
    if not a.analysis_only:
        run("verify_figures_v2.py")
        run("verify_paper_v2.py")
    assert all(
        hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == digest
        for n, digest in sources.items()
    )
    result = dict(
        status=(
            "PASS_ANALYSIS_ONLY_REPLAY"
            if a.analysis_only
            else "PASS_COMPLETE_V2_OFFLINE_REPLAY"
        ),
        python=platform.python_version(),
        exact_fields=comparison.exact,
        numeric_fields=comparison.numeric,
        independently_bounded_as_run_diagnostics=comparison.as_run,
        maximum_difference_fraction_of_declared_tolerance=str(comparison.maximum),
        phase_conditions=proofs,
        source_files_unchanged=len(sources),
        source_sha256=sources,
        source_requests=0,
        full_history_repository=True,
        fixtures=22,
        authored_cases=3,
        source="Selected public EIA facts; complete private original workbooks separately reconciled and hash-bound",
        original_v1_gate="FAILED_UNCHANGED",
    )
    (a.out / "replay_receipt.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
