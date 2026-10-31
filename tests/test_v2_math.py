"""Closed-form rational and eligibility fixtures; no recorded heat-rate outcomes."""

import sys, tempfile, unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import decompose_v2 as d


def cfg():
    return dict(
        years=[2020, 2021],
        fleets=["coal", "natural_gas", "pooled"],
        grain=["plant_fuel", "plant_technology_fuel"],
        cohorts=["pair_common", "balanced_2018_2024"],
        precision_digits=60,
        absolute_numeric_tolerance="1e-45",
        primary_minimum_matched_plants=2,
        coal_codes=["BIT"],
        natural_gas_codes=["NG"],
        combined_cycle_codes=["CA", "CT", "CS"],
        states=["NY"],
    )


def fact(plant, f, g, family="natural_gas"):
    return dict(
        plant=plant, fuel_mmbtu=str(f), net_mwh=str(g), fuel_group=family, eligible=True
    )


def fixture():
    return {
        "plant_fuel": {
            2020: {
                "1|natural_gas": fact("1", 100, 10),
                "2|natural_gas": fact("2", 200, 10),
            },
            2021: {
                "1|natural_gas": fact("1", 240, 20),
                "2|natural_gas": fact("2", 180, 10),
            },
        }
    }


def source(row, plant="1", pm="GT", fuel="NG", f="100", g="10", chp="N", state="NY"):
    return dict(
        year="2020",
        source_row=str(row),
        plant=plant,
        prime_mover=pm,
        fuel=fuel,
        elec_mmbtu_raw=f,
        net_mwh_raw=g,
        chp=chp,
        state=state,
    )


class RationalIdentities(unittest.TestCase):
    def close_fraction(self, actual, expected):
        self.assertLessEqual(
            abs(Fraction(Decimal(actual)) - Fraction(expected)), Fraction(1, 10**45)
        )

    def test_symmetric_within_and_mix_have_known_opposite_signs(self):
        out, _, _ = d.case(
            fixture(), cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["within"], Fraction(1, 3))
        self.close_fraction(out["mix"], Fraction(-4, 3))
        self.close_fraction(out["matched_change"], -1)

    def test_first_factor_path_matches_exact_rational_case(self):
        out, _, _ = d.case(
            fixture(), cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["within_initial_shares"], 0)
        self.close_fraction(out["mix_final_ratios"], -1)

    def test_second_factor_path_matches_exact_rational_case(self):
        out, _, _ = d.case(
            fixture(), cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["within_final_shares"], Fraction(2, 3))
        self.close_fraction(out["mix_initial_ratios"], Fraction(-5, 3))

    def test_symmetric_terms_are_path_averages(self):
        out, _, _ = d.case(
            fixture(), cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(
            out["within"],
            (
                Fraction(Decimal(out["within_initial_shares"]))
                + Fraction(Decimal(out["within_final_shares"]))
            )
            / 2,
        )

    def test_outside_cohort_bridge_keeps_unmatched_output(self):
        cells = fixture()
        cells["plant_fuel"][2021]["3|natural_gas"] = fact("3", 1000, 100)
        out, _, _ = d.case(
            cells, cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["full_change"], Fraction(-53, 13))
        self.close_fraction(
            out["outside_cohort_composition_remainder"], Fraction(-40, 13)
        )
        self.close_fraction(out["generation_coverage1"], Fraction(3, 13))

    def test_constant_cell_ratios_have_zero_within_term(self):
        cells = fixture()
        cells["plant_fuel"][2021]["1|natural_gas"] = fact("1", 200, 20)
        cells["plant_fuel"][2021]["2|natural_gas"] = fact("2", 200, 10)
        out, _, _ = d.case(
            cells, cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["within"], 0)

    def test_constant_shares_have_zero_mix_term(self):
        cells = fixture()
        cells["plant_fuel"][2021]["1|natural_gas"] = fact("1", 120, 10)
        out, _, _ = d.case(
            cells, cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.close_fraction(out["mix"], 0)

    def test_leave_one_plant_changes_match_direct_one_cell_case(self):
        _, _, influence = d.case(
            fixture(), cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        one = next(x for x in influence if x["removed_plant"] == "1")
        two = next(x for x in influence if x["removed_plant"] == "2")
        self.close_fraction(one["within"], -2)
        self.close_fraction(one["mix"], 0)
        self.close_fraction(two["within"], 2)
        self.close_fraction(two["mix"], 0)

    def test_pooled_deletion_removes_all_fuel_cells_of_plant(self):
        cells = fixture()
        for y in [2020, 2021]:
            cells["plant_fuel"][y]["1|coal"] = fact("1", 50, 5, "coal")
        _, _, influence = d.case(
            cells, cfg(), 2021, "pooled", "plant_fuel", "pair_common"
        )
        row = next(x for x in influence if x["removed_plant"] == "1")
        self.assertEqual(row["remaining_cells"], 1)

    def test_minimum_support_counts_plants_instead_of_fuel_cells(self):
        cells = {
            "plant_fuel": {
                2020: {
                    "1|coal": fact("1", 10, 1, "coal"),
                    "1|natural_gas": fact("1", 10, 1),
                },
                2021: {
                    "1|coal": fact("1", 10, 1, "coal"),
                    "1|natural_gas": fact("1", 10, 1),
                },
            }
        }
        out, contributions, influence = d.case(
            cells, cfg(), 2021, "pooled", "plant_fuel", "pair_common"
        )
        self.assertEqual(out["state"], "NOT_ESTIMABLE")
        self.assertEqual(contributions, [])
        self.assertEqual(influence, [])

    def test_balanced_membership_uses_all_fixed_years(self):
        cells = fixture()
        cells["plant_fuel"][2022] = {"1|natural_gas": fact("1", 200, 20)}
        c = cfg()
        c["years"] = [2020, 2021, 2022]
        _, common = d.matching(
            cells["plant_fuel"],
            2020,
            2021,
            "natural_gas",
            "balanced_2018_2024",
            c["years"],
        )
        self.assertEqual(common, ["1|natural_gas"])

    def test_empty_cohort_is_not_a_zero_change(self):
        cells = fixture()
        cells["plant_fuel"][2021] = {}
        out, _, _ = d.case(
            cells, cfg(), 2021, "natural_gas", "plant_fuel", "pair_common"
        )
        self.assertEqual(out["state"], "NOT_ESTIMABLE")
        self.assertNotIn("within", out)


class SourceEligibility(unittest.TestCase):
    def test_negative_component_is_summed_before_positivity(self):
        cells, _, _ = d.cells_from_source(
            [source(1, f="0", g="-1"), source(2, f="100", g="11")], cfg()
        )
        r = cells["plant_fuel"][2020]["1|natural_gas"]
        self.assertEqual(Decimal(r["net_mwh"]), 10)
        self.assertTrue(r["eligible"])
        self.assertEqual(r["negative_generation_components"], 1)

    def test_combined_cycle_merges_before_eligibility(self):
        cells, _, _ = d.cells_from_source(
            [source(1, pm="CA", f="0", g="5"), source(2, pm="CT", f="100", g="5")],
            cfg(),
        )
        r = cells["plant_technology_fuel"][2020]["1|CC|natural_gas"]
        self.assertTrue(r["eligible"])
        self.assertEqual(Decimal(r["net_mwh"]), 10)

    def test_missing_component_is_not_imputed_as_zero(self):
        cells, _, _ = d.cells_from_source([source(1, f=""), source(2)], cfg())
        r = cells["plant_fuel"][2020]["1|natural_gas"]
        self.assertIsNone(r["fuel_mmbtu"])
        self.assertFalse(r["eligible"])
        self.assertEqual(r["missing_fuel_components"], 1)

    def test_nonpositive_aggregate_generation_is_ineligible(self):
        cells, _, _ = d.cells_from_source(
            [source(1, g="-10"), source(2, g="10")], cfg()
        )
        r = cells["plant_fuel"][2020]["1|natural_gas"]
        self.assertFalse(r["eligible"])
        self.assertEqual(Decimal(r["net_mwh"]), 0)

    def test_unknown_chp_does_not_become_non_chp(self):
        cells, _, excluded = d.cells_from_source([source(1, chp="")], cfg())
        self.assertEqual(cells["plant_fuel"][2020], {})
        self.assertEqual(excluded[0]["reason"], "not_explicit_non_chp")

    def test_waste_heat_is_not_assigned_to_natural_gas(self):
        cells, _, excluded = d.cells_from_source(
            [source(1, fuel="WH", f="0", g="100"), source(2)], cfg()
        )
        self.assertEqual(
            Decimal(cells["plant_fuel"][2020]["1|natural_gas"]["net_mwh"]), 10
        )
        self.assertEqual(excluded[0]["reason"], "diagnostic_waste_heat")

    def test_geography_exclusion_is_explicit(self):
        cells, _, excluded = d.cells_from_source([source(1, state="PR")], cfg())
        self.assertEqual(cells["plant_fuel"][2020], {})
        self.assertEqual(excluded[0]["reason"], "outside_50_states_dc")

    def test_large_cancellation_remains_an_exact_source_sum(self):
        value = d.exact_sum([Decimal("1e40"), Decimal("1e-30"), Decimal("-1e40")])
        self.assertEqual(value, Decimal("1e-30"))

    def test_malformed_and_nonfinite_tokens_stay_unavailable(self):
        for value in ["", ".", "NaN", "Infinity"]:
            self.assertIsNone(d.number(value))

    def test_held_execution_refuses_missing_committed_freeze(self):
        with tempfile.TemporaryDirectory() as path, patch.object(d, "ROOT", Path(path)):
            with self.assertRaisesRegex(ValueError, "freeze required"):
                d.check_freeze()


if __name__ == "__main__":
    unittest.main()
