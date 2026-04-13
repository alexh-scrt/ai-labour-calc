"""Unit tests for the AI Labour Impact Calculator's calculation engine.

Covers:
- Happy-path scenario calculation correctness
- Displacement rate capping (aggressive scenario exceeding 100%)
- Zero automation potential produces zero displacement
- Full automation potential in all scenarios
- Progressive robot tax tier boundaries
- Safety-net component isolation
- Input validation: bad types, out-of-range salary, too many/few roles
- FullReport aggregation properties
- Monotonicity: aggressive >= moderate >= optimistic for displacement
"""

from __future__ import annotations

import math
import pytest

from ai_labour_calc.models import RoleInput, ScenarioResult, FullReport
from ai_labour_calc.calculator import (
    calculate_report,
    _calculate_role_displacement,
    _calculate_robot_tax,
    _calculate_safety_net,
    _validate_inputs,
    _calculate_scenario,
)
from ai_labour_calc.assumptions import (
    SCENARIOS,
    ROBOT_TAX_RATE,
    RETRAINING_COST_PER_WORKER,
    UBI_ANNUAL_TRANSFER,
    MIN_ANNUAL_SALARY,
    MAX_ANNUAL_SALARY,
    MAX_ROLE_HEADCOUNT,
    MAX_ROLES,
    get_robot_tax_rate,
    get_ui_cost_per_worker,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def single_role() -> RoleInput:
    """A single role with 100 workers and 80% automation potential."""
    return RoleInput(role_name="Data Entry", headcount=100, automation_potential=80.0)


@pytest.fixture
def multi_roles() -> list[RoleInput]:
    """A realistic mix of roles for integration-style tests."""
    return [
        RoleInput("Data Entry", 100, 80.0),
        RoleInput("Analysts", 50, 30.0),
        RoleInput("Managers", 20, 10.0),
    ]


@pytest.fixture
def base_salary() -> float:
    """Standard average annual salary used across tests."""
    return 55_000.0


@pytest.fixture
def full_report(multi_roles, base_salary) -> FullReport:
    """Pre-computed FullReport for the standard multi-role fixture."""
    return calculate_report(
        roles=multi_roles,
        average_annual_salary=base_salary,
        organisation_name="Test Corp",
    )


# --------------------------------------------------------------------------- #
# RoleInput validation                                                         #
# --------------------------------------------------------------------------- #


class TestRoleInputValidation:
    def test_valid_role_creation(self) -> None:
        role = RoleInput("Engineers", 50, 25.0)
        assert role.role_name == "Engineers"
        assert role.headcount == 50
        assert role.automation_potential == 25.0

    def test_zero_headcount_is_valid(self) -> None:
        role = RoleInput("Empty Role", 0, 50.0)
        assert role.headcount == 0

    def test_zero_automation_is_valid(self) -> None:
        role = RoleInput("Surgeons", 10, 0.0)
        assert role.automation_potential == 0.0

    def test_full_automation_is_valid(self) -> None:
        role = RoleInput("Data Entry", 10, 100.0)
        assert role.automation_potential == 100.0

    def test_negative_headcount_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            RoleInput("Bad Role", -1, 50.0)

    def test_automation_over_100_raises(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            RoleInput("Bad Role", 10, 101.0)

    def test_automation_below_0_raises(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            RoleInput("Bad Role", 10, -1.0)

    def test_empty_role_name_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            RoleInput("", 10, 50.0)

    def test_whitespace_role_name_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            RoleInput("   ", 10, 50.0)

    def test_boundary_automation_0(self) -> None:
        role = RoleInput("Test", 5, 0.0)
        assert role.automation_potential == 0.0

    def test_boundary_automation_100(self) -> None:
        role = RoleInput("Test", 5, 100.0)
        assert role.automation_potential == 100.0

    def test_boundary_headcount_0(self) -> None:
        role = RoleInput("Test", 0, 50.0)
        assert role.headcount == 0

    def test_fractional_automation_potential(self) -> None:
        role = RoleInput("Test", 10, 33.7)
        assert math.isclose(role.automation_potential, 33.7)


# --------------------------------------------------------------------------- #
# _calculate_role_displacement                                                 #
# --------------------------------------------------------------------------- #


class TestRoleDisplacement:
    def test_moderate_scenario_basic(self, single_role) -> None:
        # multiplier=1.0, potential=80% => effective_rate=0.8, displaced=80
        result = _calculate_role_displacement(single_role, 1.0)
        assert result.displaced_workers == 80
        assert result.remaining_workers == 20
        assert result.original_headcount == 100
        assert math.isclose(result.displacement_rate, 0.8)

    def test_optimistic_halves_displacement(self, single_role) -> None:
        # multiplier=0.5, potential=80% => effective_rate=0.4, displaced=40
        result = _calculate_role_displacement(single_role, 0.5)
        assert result.displaced_workers == 40
        assert result.remaining_workers == 60

    def test_aggressive_caps_at_100_percent(self) -> None:
        # multiplier=1.5, potential=80% => raw=1.2 => capped at 1.0
        role = RoleInput("Telemarketers", 200, 80.0)
        result = _calculate_role_displacement(role, 1.5)
        assert result.displacement_rate == 1.0
        assert result.displaced_workers == 200
        assert result.remaining_workers == 0

    def test_zero_automation_potential(self) -> None:
        role = RoleInput("Surgeons", 50, 0.0)
        result = _calculate_role_displacement(role, 1.5)
        assert result.displaced_workers == 0
        assert result.remaining_workers == 50

    def test_zero_headcount(self) -> None:
        role = RoleInput("Future Role", 0, 100.0)
        result = _calculate_role_displacement(role, 1.5)
        assert result.displaced_workers == 0
        assert result.remaining_workers == 0

    def test_floor_behaviour_for_fractional_displacement(self) -> None:
        # 3 workers * 33.3% => 0.999 => floor => 0
        role = RoleInput("Tiny Team", 3, 33.3)
        result = _calculate_role_displacement(role, 1.0)
        assert result.displaced_workers == 0

    def test_role_name_preserved(self, single_role) -> None:
        result = _calculate_role_displacement(single_role, 1.0)
        assert result.role_name == single_role.role_name

    def test_displaced_never_exceeds_headcount(self) -> None:
        role = RoleInput("Clerks", 77, 100.0)
        result = _calculate_role_displacement(role, 2.0)  # extreme multiplier
        assert result.displaced_workers <= role.headcount

    def test_displaced_plus_remaining_equals_headcount(self) -> None:
        role = RoleInput("Workers", 150, 65.0)
        result = _calculate_role_displacement(role, 1.0)
        assert result.displaced_workers + result.remaining_workers == role.headcount

    def test_effective_rate_stored_correctly(self) -> None:
        role = RoleInput("Clerks", 100, 60.0)
        result = _calculate_role_displacement(role, 1.0)
        assert math.isclose(result.displacement_rate, 0.6, rel_tol=1e-5)

    def test_aggressive_100pct_potential_displaces_all(self) -> None:
        role = RoleInput("Bots", 500, 100.0)
        result = _calculate_role_displacement(role, 1.5)
        assert result.displaced_workers == 500
        assert result.displacement_rate == 1.0

    def test_low_multiplier_low_displacement(self) -> None:
        role = RoleInput("Artisans", 100, 20.0)
        result = _calculate_role_displacement(role, 0.5)
        # effective_rate = 0.1, displaced = floor(100 * 0.1) = 10
        assert result.displaced_workers == 10

    def test_single_worker_partial_rate_floors_to_zero(self) -> None:
        role = RoleInput("Solo", 1, 50.0)
        result = _calculate_role_displacement(role, 1.0)
        # floor(1 * 0.5) = 0
        assert result.displaced_workers == 0

    def test_single_worker_full_rate_displaces_one(self) -> None:
        role = RoleInput("Solo", 1, 100.0)
        result = _calculate_role_displacement(role, 1.0)
        assert result.displaced_workers == 1


# --------------------------------------------------------------------------- #
# _calculate_robot_tax                                                         #
# --------------------------------------------------------------------------- #


class TestRobotTax:
    def test_zero_displaced_returns_zero(self) -> None:
        assert _calculate_robot_tax(0, 60_000.0, ROBOT_TAX_RATE) == 0.0

    def test_basic_calculation(self) -> None:
        # 100 displaced * $50,000 * 10% = $500,000
        result = _calculate_robot_tax(100, 50_000.0, 0.10)
        assert math.isclose(result, 500_000.0)

    def test_progressive_rate_applied(self) -> None:
        # 300 displaced => rate = 0.12 (10% base + 2% surcharge)
        rate = get_robot_tax_rate(300)
        assert math.isclose(rate, 0.12)
        result = _calculate_robot_tax(300, 50_000.0, rate)
        assert math.isclose(result, 300 * 50_000.0 * 0.12)

    def test_scales_linearly_with_displaced(self) -> None:
        rate = ROBOT_TAX_RATE
        r1 = _calculate_robot_tax(50, 40_000.0, rate)
        r2 = _calculate_robot_tax(100, 40_000.0, rate)
        assert math.isclose(r2, r1 * 2)

    def test_negative_displaced_treated_as_zero(self) -> None:
        # The function checks > 0, so negative values return 0
        result = _calculate_robot_tax(-5, 60_000.0, 0.10)
        assert result == 0.0

    def test_high_salary_scales_tax(self) -> None:
        r_low = _calculate_robot_tax(100, 30_000.0, 0.10)
        r_high = _calculate_robot_tax(100, 90_000.0, 0.10)
        assert math.isclose(r_high, r_low * 3)

    def test_high_tax_rate(self) -> None:
        result = _calculate_robot_tax(10, 50_000.0, 0.15)
        assert math.isclose(result, 10 * 50_000.0 * 0.15)


class TestProgressiveTaxRate:
    @pytest.mark.parametrize("count, expected_rate", [
        (0, 0.10),
        (49, 0.10),
        (50, 0.11),
        (249, 0.11),
        (250, 0.12),
        (499, 0.12),
        (500, 0.13),
        (999, 0.13),
        (1000, 0.15),
        (9999, 0.15),
    ])
    def test_tier_boundaries(self, count: int, expected_rate: float) -> None:
        assert math.isclose(get_robot_tax_rate(count), expected_rate), (
            f"displaced={count}: expected {expected_rate}, "
            f"got {get_robot_tax_rate(count)}"
        )

    def test_rate_never_below_base(self) -> None:
        for count in [0, 1, 10, 49]:
            assert get_robot_tax_rate(count) >= ROBOT_TAX_RATE

    def test_rate_monotonically_non_decreasing(self) -> None:
        counts = [0, 49, 50, 249, 250, 499, 500, 999, 1000, 5000]
        rates = [get_robot_tax_rate(c) for c in counts]
        for i in range(len(rates) - 1):
            assert rates[i] <= rates[i + 1], (
                f"Rate decreased from count={counts[i]} to count={counts[i+1]}"
            )


# --------------------------------------------------------------------------- #
# _calculate_safety_net                                                        #
# --------------------------------------------------------------------------- #


class TestSafetyNet:
    def test_zero_displaced_returns_zeros(self) -> None:
        r, u, ui = _calculate_safety_net(0, 60_000.0)
        assert r == 0.0
        assert u == 0.0
        assert ui == 0.0

    def test_retraining_cost_correct(self) -> None:
        retraining, _, _ = _calculate_safety_net(10, 50_000.0)
        assert math.isclose(retraining, 10 * RETRAINING_COST_PER_WORKER)

    def test_ubi_annual_transfer_correct(self) -> None:
        _, ubi, _ = _calculate_safety_net(10, 50_000.0)
        assert math.isclose(ubi, 10 * UBI_ANNUAL_TRANSFER)

    def test_ui_cost_correct(self) -> None:
        salary = 60_000.0
        expected_per_worker = get_ui_cost_per_worker(salary)
        _, _, ui = _calculate_safety_net(5, salary)
        assert math.isclose(ui, 5 * expected_per_worker)

    def test_get_ui_cost_per_worker(self) -> None:
        # monthly = 60000/12 = 5000, UI = 5000 * 0.5 * 6 = 15000
        result = get_ui_cost_per_worker(60_000.0)
        assert math.isclose(result, 15_000.0)

    def test_components_all_non_negative(self) -> None:
        r, u, ui = _calculate_safety_net(25, 45_000.0)
        assert r >= 0 and u >= 0 and ui >= 0

    def test_scales_linearly_with_displaced(self) -> None:
        r1, u1, ui1 = _calculate_safety_net(10, 50_000.0)
        r2, u2, ui2 = _calculate_safety_net(20, 50_000.0)
        assert math.isclose(r2, r1 * 2)
        assert math.isclose(u2, u1 * 2)
        assert math.isclose(ui2, ui1 * 2)

    def test_ui_scales_with_salary(self) -> None:
        _, _, ui_low = _calculate_safety_net(10, 30_000.0)
        _, _, ui_high = _calculate_safety_net(10, 60_000.0)
        assert math.isclose(ui_high, ui_low * 2)

    def test_retraining_does_not_scale_with_salary(self) -> None:
        r_low, _, _ = _calculate_safety_net(10, 30_000.0)
        r_high, _, _ = _calculate_safety_net(10, 300_000.0)
        # Retraining is salary-independent
        assert math.isclose(r_low, r_high)

    def test_ubi_does_not_scale_with_salary(self) -> None:
        _, u_low, _ = _calculate_safety_net(5, 20_000.0)
        _, u_high, _ = _calculate_safety_net(5, 200_000.0)
        assert math.isclose(u_low, u_high)

    def test_large_displaced_count(self) -> None:
        r, u, ui = _calculate_safety_net(10_000, 55_000.0)
        assert r == 10_000 * RETRAINING_COST_PER_WORKER
        assert u == 10_000 * UBI_ANNUAL_TRANSFER


# --------------------------------------------------------------------------- #
# _validate_inputs                                                             #
# --------------------------------------------------------------------------- #


class TestValidateInputs:
    def test_valid_inputs_pass_silently(self, multi_roles, base_salary) -> None:
        _validate_inputs(multi_roles, base_salary, "ACME")

    def test_non_list_roles_raises_type_error(self, base_salary) -> None:
        with pytest.raises(TypeError, match="list"):
            _validate_inputs("not a list", base_salary, "Org")  # type: ignore

    def test_empty_roles_raises_value_error(self, base_salary) -> None:
        with pytest.raises(ValueError, match="least"):
            _validate_inputs([], base_salary, "Org")

    def test_too_many_roles_raises_value_error(self, base_salary) -> None:
        roles = [RoleInput(f"Role {i}", 10, 50.0) for i in range(MAX_ROLES + 1)]
        with pytest.raises(ValueError, match="maximum"):
            _validate_inputs(roles, base_salary, "Org")

    def test_role_not_roleinput_raises_type_error(self, base_salary) -> None:
        with pytest.raises(TypeError, match="RoleInput"):
            _validate_inputs([{"role_name": "Bad"}], base_salary, "Org")  # type: ignore

    def test_headcount_exceeds_max_raises_value_error(self, base_salary) -> None:
        role = RoleInput("Huge Role", MAX_ROLE_HEADCOUNT + 1, 50.0)
        with pytest.raises(ValueError, match="exceeds"):
            _validate_inputs([role], base_salary, "Org")

    def test_salary_below_minimum_raises_value_error(self, multi_roles) -> None:
        with pytest.raises(ValueError, match="least"):
            _validate_inputs(multi_roles, MIN_ANNUAL_SALARY - 1, "Org")

    def test_salary_above_maximum_raises_value_error(self, multi_roles) -> None:
        with pytest.raises(ValueError, match="exceed"):
            _validate_inputs(multi_roles, MAX_ANNUAL_SALARY + 1, "Org")

    def test_nan_salary_raises_value_error(self, multi_roles) -> None:
        with pytest.raises(ValueError, match="finite"):
            _validate_inputs(multi_roles, float("nan"), "Org")

    def test_inf_salary_raises_value_error(self, multi_roles) -> None:
        with pytest.raises(ValueError, match="finite"):
            _validate_inputs(multi_roles, float("inf"), "Org")

    def test_non_string_org_name_raises_type_error(self, multi_roles, base_salary) -> None:
        with pytest.raises(TypeError, match="string"):
            _validate_inputs(multi_roles, base_salary, 42)  # type: ignore

    def test_salary_at_minimum_boundary_passes(self, multi_roles) -> None:
        _validate_inputs(multi_roles, MIN_ANNUAL_SALARY, "Org")

    def test_salary_at_maximum_boundary_passes(self, multi_roles) -> None:
        _validate_inputs(multi_roles, MAX_ANNUAL_SALARY, "Org")

    def test_exactly_max_roles_passes(self, base_salary) -> None:
        roles = [RoleInput(f"Role {i}", 10, 50.0) for i in range(MAX_ROLES)]
        _validate_inputs(roles, base_salary, "Org")  # should not raise

    def test_tuple_roles_raises_type_error(self, base_salary) -> None:
        with pytest.raises(TypeError, match="list"):
            _validate_inputs((RoleInput("A", 1, 10.0),), base_salary, "Org")  # type: ignore

    def test_none_roles_raises_type_error(self, base_salary) -> None:
        with pytest.raises(TypeError, match="list"):
            _validate_inputs(None, base_salary, "Org")  # type: ignore

    def test_integer_salary_passes(self, multi_roles) -> None:
        # int is acceptable for average_annual_salary
        _validate_inputs(multi_roles, int(MIN_ANNUAL_SALARY), "Org")

    def test_negative_inf_salary_raises(self, multi_roles) -> None:
        with pytest.raises(ValueError, match="finite"):
            _validate_inputs(multi_roles, float("-inf"), "Org")


# --------------------------------------------------------------------------- #
# calculate_report — integration-level tests                                  #
# --------------------------------------------------------------------------- #


class TestCalculateReport:
    def test_returns_full_report(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary)
        assert isinstance(report, FullReport)

    def test_organisation_name_stored(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary, "Globex")
        assert report.organisation_name == "Globex"

    def test_all_three_scenarios_present(self, full_report) -> None:
        assert isinstance(full_report.optimistic, ScenarioResult)
        assert isinstance(full_report.moderate, ScenarioResult)
        assert isinstance(full_report.aggressive, ScenarioResult)

    def test_scenario_names(self, full_report) -> None:
        assert full_report.optimistic.scenario_name == "Optimistic"
        assert full_report.moderate.scenario_name == "Moderate"
        assert full_report.aggressive.scenario_name == "Aggressive"

    def test_total_headcount_consistent_across_scenarios(self, full_report) -> None:
        hc = full_report.optimistic.total_headcount
        assert full_report.moderate.total_headcount == hc
        assert full_report.aggressive.total_headcount == hc

    def test_total_headcount_matches_input(self, multi_roles, base_salary) -> None:
        total = sum(r.headcount for r in multi_roles)
        report = calculate_report(multi_roles, base_salary)
        assert report.total_headcount == total

    def test_monotonicity_displaced(self, full_report) -> None:
        """Aggressive must displace >= moderate >= optimistic."""
        assert (
            full_report.optimistic.total_displaced
            <= full_report.moderate.total_displaced
            <= full_report.aggressive.total_displaced
        )

    def test_monotonicity_robot_tax(self, full_report) -> None:
        assert (
            full_report.optimistic.robot_tax_liability
            <= full_report.moderate.robot_tax_liability
            <= full_report.aggressive.robot_tax_liability
        )

    def test_monotonicity_safety_net(self, full_report) -> None:
        assert (
            full_report.optimistic.total_safety_net_exposure
            <= full_report.moderate.total_safety_net_exposure
            <= full_report.aggressive.total_safety_net_exposure
        )

    def test_displacement_percentage_range(self, full_report) -> None:
        for scenario in full_report.all_scenarios:
            assert 0.0 <= scenario.displacement_percentage <= 100.0

    def test_remaining_plus_displaced_equals_headcount(self, full_report) -> None:
        for scenario in full_report.all_scenarios:
            assert scenario.total_remaining + scenario.total_displaced == scenario.total_headcount

    def test_role_breakdowns_count_matches_input(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary)
        for scenario in report.all_scenarios:
            assert len(scenario.role_breakdowns) == len(multi_roles)

    def test_safety_net_components_sum_to_total(self, full_report) -> None:
        for scenario in full_report.all_scenarios:
            expected = (
                scenario.retraining_cost
                + scenario.ubi_transfer_annual
                + scenario.unemployment_insurance_cost
            )
            assert math.isclose(
                scenario.total_safety_net_exposure, expected, rel_tol=1e-6
            )

    def test_total_financial_exposure_property(self, full_report) -> None:
        for scenario in full_report.all_scenarios:
            expected = scenario.robot_tax_liability + scenario.total_safety_net_exposure
            assert math.isclose(scenario.total_financial_exposure, expected)

    def test_zero_automation_potential_no_displacement(self, base_salary) -> None:
        roles = [RoleInput("Surgeons", 100, 0.0), RoleInput("Judges", 50, 0.0)]
        report = calculate_report(roles, base_salary)
        for scenario in report.all_scenarios:
            assert scenario.total_displaced == 0
            assert scenario.robot_tax_liability == 0.0
            assert scenario.total_safety_net_exposure == 0.0

    def test_full_automation_aggressive_displaces_all(self, base_salary) -> None:
        roles = [RoleInput("Clerks", 200, 100.0)]
        report = calculate_report(roles, base_salary)
        # Aggressive multiplier=1.5 => effective_rate=min(1.5,1.0)=1.0 => all displaced
        assert report.aggressive.total_displaced == 200
        assert report.aggressive.total_remaining == 0

    def test_single_role_report(self, base_salary) -> None:
        roles = [RoleInput("Solo", 10, 50.0)]
        report = calculate_report(roles, base_salary)
        assert report.optimistic.total_headcount == 10

    def test_max_roles_boundary(self, base_salary) -> None:
        roles = [RoleInput(f"Role {i}", 10, 50.0) for i in range(MAX_ROLES)]
        report = calculate_report(roles, base_salary)
        assert report.total_headcount == 10 * MAX_ROLES

    def test_default_org_name(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary)
        assert isinstance(report.organisation_name, str)
        assert len(report.organisation_name) > 0

    def test_all_scenarios_list_order(self, full_report) -> None:
        scenarios = full_report.all_scenarios
        assert scenarios[0].scenario_name == "Optimistic"
        assert scenarios[1].scenario_name == "Moderate"
        assert scenarios[2].scenario_name == "Aggressive"

    def test_max_displaced_property(self, full_report) -> None:
        assert full_report.max_displaced == full_report.aggressive.total_displaced

    def test_max_financial_exposure_property(self, full_report) -> None:
        assert full_report.max_financial_exposure == full_report.aggressive.total_financial_exposure

    def test_roles_preserved_in_report(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary)
        assert len(report.roles) == len(multi_roles)
        for original, stored in zip(multi_roles, report.roles):
            assert original.role_name == stored.role_name
            assert original.headcount == stored.headcount

    def test_displacement_percentage_zero_headcount_edge_case(self, base_salary) -> None:
        """A role with 0 headcount should not cause division by zero."""
        roles = [RoleInput("Ghost Team", 0, 80.0)]
        report = calculate_report(roles, base_salary)
        for scenario in report.all_scenarios:
            assert scenario.displacement_percentage == 0.0

    def test_high_salary_robot_tax_scales(self, multi_roles) -> None:
        report_low = calculate_report(multi_roles, 50_000.0)
        report_high = calculate_report(multi_roles, 100_000.0)
        # Robot tax should be higher with higher salary (assuming same displaced count)
        assert (
            report_high.moderate.robot_tax_liability
            >= report_low.moderate.robot_tax_liability
        )

    def test_scenario_timeline_years_values(self, full_report) -> None:
        assert full_report.optimistic.timeline_years == 10
        assert full_report.moderate.timeline_years == 7
        assert full_report.aggressive.timeline_years == 4

    def test_scenario_multiplier_values(self, full_report) -> None:
        assert math.isclose(full_report.optimistic.timeline_multiplier, 0.5)
        assert math.isclose(full_report.moderate.timeline_multiplier, 1.0)
        assert math.isclose(full_report.aggressive.timeline_multiplier, 1.5)

    def test_moderate_calculation_correctness(self, base_salary) -> None:
        """Manually verify moderate scenario arithmetic."""
        roles = [RoleInput("Data Entry", 100, 80.0)]
        report = calculate_report(roles, base_salary)
        moderate = report.moderate

        # multiplier=1.0, potential=80% => displaced = floor(100*0.8) = 80
        assert moderate.total_displaced == 80
        assert moderate.total_remaining == 20

        # progressive rate for 80 displaced = 0.11 (50–249 tier)
        expected_tax_rate = get_robot_tax_rate(80)
        assert math.isclose(expected_tax_rate, 0.11)
        expected_tax = 80 * base_salary * expected_tax_rate
        assert math.isclose(moderate.robot_tax_liability, round(expected_tax, 2), rel_tol=1e-5)

        # retraining = 80 * 15000 = 1,200,000
        assert math.isclose(moderate.retraining_cost, 80 * RETRAINING_COST_PER_WORKER)

        # UBI = 80 * 12000 = 960,000
        assert math.isclose(moderate.ubi_transfer_annual, 80 * UBI_ANNUAL_TRANSFER)

        # UI = 80 * get_ui_cost_per_worker(55000)
        expected_ui = 80 * get_ui_cost_per_worker(base_salary)
        assert math.isclose(moderate.unemployment_insurance_cost, round(expected_ui, 2), rel_tol=1e-5)

    def test_optimistic_calculation_correctness(self, base_salary) -> None:
        """Manually verify optimistic scenario arithmetic."""
        roles = [RoleInput("Data Entry", 100, 80.0)]
        report = calculate_report(roles, base_salary)
        optimistic = report.optimistic

        # multiplier=0.5, potential=80% => displaced = floor(100*0.4) = 40
        assert optimistic.total_displaced == 40
        assert optimistic.total_remaining == 60

    def test_aggressive_calculation_correctness(self, base_salary) -> None:
        """Manually verify aggressive scenario arithmetic."""
        roles = [RoleInput("Data Entry", 100, 80.0)]
        report = calculate_report(roles, base_salary)
        aggressive = report.aggressive

        # multiplier=1.5, potential=80% => raw=1.2 => capped=1.0 => displaced=100
        assert aggressive.total_displaced == 100
        assert aggressive.total_remaining == 0

    def test_mixed_roles_sum_correctly(self, base_salary) -> None:
        roles = [
            RoleInput("High", 100, 90.0),
            RoleInput("Low", 100, 10.0),
        ]
        report = calculate_report(roles, base_salary)
        moderate = report.moderate
        # High: floor(100 * 0.9) = 90, Low: floor(100 * 0.1) = 10
        assert moderate.total_displaced == 100
        assert moderate.total_headcount == 200

    def test_roles_list_is_copy_not_reference(self, multi_roles, base_salary) -> None:
        """Mutating the input list after calculation should not affect the report."""
        report = calculate_report(multi_roles, base_salary)
        original_count = len(report.roles)
        multi_roles.append(RoleInput("New Role", 5, 50.0))
        assert len(report.roles) == original_count

    def test_all_zero_headcount_roles(self, base_salary) -> None:
        roles = [RoleInput("Ghost", 0, 100.0), RoleInput("Empty", 0, 50.0)]
        report = calculate_report(roles, base_salary)
        for scenario in report.all_scenarios:
            assert scenario.total_headcount == 0
            assert scenario.total_displaced == 0
            assert scenario.displacement_percentage == 0.0

    def test_robot_tax_zero_when_no_displacement(self, base_salary) -> None:
        roles = [RoleInput("Protected", 100, 0.0)]
        report = calculate_report(roles, base_salary)
        for scenario in report.all_scenarios:
            assert scenario.robot_tax_liability == 0.0

    def test_safety_net_zero_when_no_displacement(self, base_salary) -> None:
        roles = [RoleInput("Protected", 100, 0.0)]
        report = calculate_report(roles, base_salary)
        for scenario in report.all_scenarios:
            assert scenario.retraining_cost == 0.0
            assert scenario.ubi_transfer_annual == 0.0
            assert scenario.unemployment_insurance_cost == 0.0
            assert scenario.total_safety_net_exposure == 0.0

    def test_large_workforce_calculation(self, base_salary) -> None:
        roles = [RoleInput("Mass Workers", 500_000, 50.0)]
        report = calculate_report(roles, base_salary)
        moderate = report.moderate
        # floor(500_000 * 0.5) = 250_000
        assert moderate.total_displaced == 250_000

    def test_report_average_salary_stored(self, multi_roles, base_salary) -> None:
        report = calculate_report(multi_roles, base_salary)
        assert math.isclose(report.average_annual_salary, base_salary)

    def test_total_headcount_property_matches_optimistic(self, full_report) -> None:
        assert full_report.total_headcount == full_report.optimistic.total_headcount

    def test_calculate_scenario_matches_calculate_report(self, multi_roles, base_salary) -> None:
        """_calculate_scenario results should match the scenario in the full report."""
        full_report = calculate_report(multi_roles, base_salary)
        moderate_def = next(s for s in SCENARIOS if s["key"] == "moderate")
        direct = _calculate_scenario(
            scenario_def=moderate_def,
            roles=multi_roles,
            average_annual_salary=base_salary,
        )
        assert direct.total_displaced == full_report.moderate.total_displaced
        assert math.isclose(
            direct.robot_tax_liability,
            full_report.moderate.robot_tax_liability,
            rel_tol=1e-9,
        )
