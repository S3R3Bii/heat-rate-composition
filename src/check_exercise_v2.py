"""Closed-form authored bridge reviews; no EIA outcomes used."""

import json
from review_cli_v2 import assess


def main():
    row = dict(
        state="ESTIMABLE",
        within="0.1",
        mix="-0.2",
        outside_cohort_composition_remainder="-0.01",
        full_change="-0.11",
    )
    good = assess(row)
    assert (
        good["status"] == "PASS_SUPPLIED_BRIDGE"
        and good["within_and_mix_oppose"] is True
    )
    broken = assess(dict(row, full_change="-0.1"))
    assert broken["status"] == "FAIL_SUPPLIED_BRIDGE"
    missing = assess(dict(row, within=None))
    assert missing["status"] == "UNAVAILABLE_COMPONENTS"
    print(
        json.dumps(
            dict(
                status="PASS_THREE_AUTHORED_BRIDGE_REVIEWS",
                conditions=4,
                cases=3,
                provenance="Authored decimal components; not reported EIA observations",
            )
        )
    )


if __name__ == "__main__":
    main()
