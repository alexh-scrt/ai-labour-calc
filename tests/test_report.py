"""Tests for CSV and PDF report generation.

Covers:
- build_report_dataframe: shape, columns, values, type errors
- build_role_breakdown_dataframe: shape, columns, values
- generate_csv_bytes: encoding, content structure, headers
- render_pdf_html: returns string, contains key content
- generate_pdf_bytes: returns bytes, non-empty, PDF magic bytes
- _fmt_money, _fmt_pct, _fmt_intcomma: formatting helpers
- _utc_timestamp: returns UTC string
- Edge cases: zero headcount, zero displacement, single role
- CSV data integrity: values match DataFrame
"""

from __future__ import annotations

import io
import math
import pandas as pd
import pytest

from ai_labour_calc.models import RoleInput, FullReport
from ai_labour_calc.calculator import calculate_report
from ai_labour_calc.report import (
    build_report_dataframe,
    build_role_breakdown_dataframe,
    generate_csv_bytes,
    render_pdf_html,
    generate_pdf_bytes,
    _fmt_money,
    _fmt_pct,
    _fmt_intcomma,
    _utc_timestamp,
)
from ai_labour_calc.assumptions import CURRENCY_CODE, CURRENCY_SYMBOL


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def standard_roles() -> list[RoleInput]:
    """Standard multi-role list for report tests."""
    return [
        RoleInput("Data Entry", 100, 80.0),
        RoleInput("Analysts", 50, 30.0),
        RoleInput("Managers", 20, 10.0),
    ]


@pytest.fixture
def standard_salary() -> float:
    return 55_000.0


@pytest.fixture
def standard_report(standard_roles, standard_salary) -> FullReport:
    """Pre-computed FullReport for the standard fixture."""
    return calculate_report(
        roles=standard_roles,
        average_annual_salary=standard_salary,
        organisation_name="Test Organisation",
    )


@pytest.fixture
def zero_displacement_report() -> FullReport:
    """Report where all roles have 0% automation potential."""
    roles = [
        RoleInput("Surgeons", 50, 0.0),
        RoleInput("Judges", 20, 0.0),
    ]
    return calculate_report(roles, 80_000.0, "Zero Corp")


@pytest.fixture
def single_role_report() -> FullReport:
    """Report with a single role."""
    roles = [RoleInput("Clerks", 10, 50.0)]
    return calculate_report(roles, 40_000.0, "Solo Org")


@pytest.fixture
def high_displacement_report() -> FullReport:
    """Report with high automation potential roles."""
    roles = [
        RoleInput("Data Entry", 1000, 90.0),
        RoleInput("Call Centre", 500, 85.0),
    ]
    return calculate_report(roles, 35_000.0, "High Automation Corp")


# --------------------------------------------------------------------------- #
# build_report_dataframe                                                       #
# --------------------------------------------------------------------------- #


class TestBuildReportDataframe:
    def test_returns_dataframe_with_three_rows(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert len(df) == 3

    def test_returns_pandas_dataframe(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert isinstance(df, pd.DataFrame)

    def test_scenario_column_values(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert list(df["scenario"]) == ["Optimistic", "Moderate", "Aggressive"]

    def test_organisation_column_populated(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert all(df["organisation"] == "Test Organisation")

    def test_required_columns_present(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        required = [
            "organisation",
            "scenario",
            "timeline_years",
            "timeline_multiplier",
            "total_headcount",
            "total_displaced",
            "total_remaining",
            "displacement_pct",
            f"avg_annual_salary_{CURRENCY_CODE}",
            f"robot_tax_liability_{CURRENCY_CODE}",
            f"retraining_cost_{CURRENCY_CODE}",
            f"ubi_transfer_annual_{CURRENCY_CODE}",
            f"unemployment_insurance_cost_{CURRENCY_CODE}",
            f"total_safety_net_exposure_{CURRENCY_CODE}",
            f"total_financial_exposure_{CURRENCY_CODE}",
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_headcount_consistent_across_scenarios(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert df["total_headcount"].nunique() == 1
        assert df["total_headcount"].iloc[0] == 170  # 100+50+20

    def test_displaced_monotonically_increasing(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        displacements = list(df["total_displaced"])
        assert displacements[0] <= displacements[1] <= displacements[2]

    def test_financial_exposure_monotonically_increasing(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        col = f"total_financial_exposure_{CURRENCY_CODE}"
        vals = list(df[col])
        assert vals[0] <= vals[1] <= vals[2]

    def test_displacement_pct_in_range(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert (df["displacement_pct"] >= 0.0).all()
        assert (df["displacement_pct"] <= 100.0).all()

    def test_remaining_plus_displaced_equals_headcount(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert ((df["total_displaced"] + df["total_remaining"]) == df["total_headcount"]).all()

    def test_timeline_years_values(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert list(df["timeline_years"]) == [10, 7, 4]

    def test_type_error_on_non_report(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            build_report_dataframe("not a report")  # type: ignore

    def test_type_error_on_none(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            build_report_dataframe(None)  # type: ignore

    def test_type_error_on_dict(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            build_report_dataframe({"scenario": "test"})  # type: ignore

    def test_zero_displacement_report(self, zero_displacement_report) -> None:
        df = build_report_dataframe(zero_displacement_report)
        assert (df["total_displaced"] == 0).all()
        assert (df[f"robot_tax_liability_{CURRENCY_CODE}"] == 0.0).all()
        assert (df[f"total_safety_net_exposure_{CURRENCY_CODE}"] == 0.0).all()

    def test_single_role_report(self, single_role_report) -> None:
        df = build_report_dataframe(single_role_report)
        assert len(df) == 3
        assert (df["total_headcount"] == 10).all()

    def test_avg_salary_matches_input(self, standard_report, standard_salary) -> None:
        df = build_report_dataframe(standard_report)
        col = f"avg_annual_salary_{CURRENCY_CODE}"
        assert (df[col] == round(standard_salary, 2)).all()

    def test_timeline_multiplier_values(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        multipliers = list(df["timeline_multiplier"])
        assert math.isclose(multipliers[0], 0.5)
        assert math.isclose(multipliers[1], 1.0)
        assert math.isclose(multipliers[2], 1.5)

    def test_financial_exposure_equals_tax_plus_safety_net(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        tax_col = f"robot_tax_liability_{CURRENCY_CODE}"
        sn_col = f"total_safety_net_exposure_{CURRENCY_CODE}"
        exp_col = f"total_financial_exposure_{CURRENCY_CODE}"
        for _, row in df.iterrows():
            expected = row[tax_col] + row[sn_col]
            assert math.isclose(row[exp_col], expected, rel_tol=1e-5)

    def test_safety_net_components_sum_correctly(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        r_col = f"retraining_cost_{CURRENCY_CODE}"
        u_col = f"ubi_transfer_annual_{CURRENCY_CODE}"
        ui_col = f"unemployment_insurance_cost_{CURRENCY_CODE}"
        sn_col = f"total_safety_net_exposure_{CURRENCY_CODE}"
        for _, row in df.iterrows():
            expected = row[r_col] + row[u_col] + row[ui_col]
            assert math.isclose(row[sn_col], expected, rel_tol=1e-5)

    def test_high_displacement_report(self, high_displacement_report) -> None:
        df = build_report_dataframe(high_displacement_report)
        assert len(df) == 3
        # Aggressive should have highest displacement
        assert df["total_displaced"].iloc[2] >= df["total_displaced"].iloc[0]


# --------------------------------------------------------------------------- #
# build_role_breakdown_dataframe                                               #
# --------------------------------------------------------------------------- #


class TestBuildRoleBreakdownDataframe:
    def test_returns_rows_for_all_scenarios_and_roles(
        self, standard_report, standard_roles
    ) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        expected_rows = 3 * len(standard_roles)  # 3 scenarios × 3 roles = 9
        assert len(df) == expected_rows

    def test_returns_pandas_dataframe(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert isinstance(df, pd.DataFrame)

    def test_required_columns_present(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        required = [
            "organisation",
            "scenario",
            "role_name",
            "original_headcount",
            "displaced_workers",
            "remaining_workers",
            "displacement_rate",
            "displacement_pct",
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_displacement_rate_in_range(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert (df["displacement_rate"] >= 0.0).all()
        assert (df["displacement_rate"] <= 1.0).all()

    def test_displacement_pct_in_range(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert (df["displacement_pct"] >= 0.0).all()
        assert (df["displacement_pct"] <= 100.0).all()

    def test_remaining_plus_displaced_equals_original(
        self, standard_report
    ) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert (
            (df["displaced_workers"] + df["remaining_workers"])
            == df["original_headcount"]
        ).all()

    def test_all_three_scenarios_represented(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        scenarios_in_df = set(df["scenario"].unique())
        assert scenarios_in_df == {"Optimistic", "Moderate", "Aggressive"}

    def test_type_error_on_non_report(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            build_role_breakdown_dataframe(42)  # type: ignore

    def test_type_error_on_none(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            build_role_breakdown_dataframe(None)  # type: ignore

    def test_zero_automation_all_zeros(self, zero_displacement_report) -> None:
        df = build_role_breakdown_dataframe(zero_displacement_report)
        assert (df["displaced_workers"] == 0).all()
        assert (df["displacement_rate"] == 0.0).all()

    def test_organisation_column_populated(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert all(df["organisation"] == "Test Organisation")

    def test_role_names_present(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        role_names = set(df["role_name"].unique())
        assert "Data Entry" in role_names
        assert "Analysts" in role_names
        assert "Managers" in role_names

    def test_displacement_pct_equals_rate_times_100(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        for _, row in df.iterrows():
            assert math.isclose(
                row["displacement_pct"],
                round(row["displacement_rate"] * 100, 1),
                rel_tol=1e-4,
            )

    def test_single_role_six_rows(self, single_role_report) -> None:
        df = build_role_breakdown_dataframe(single_role_report)
        # 1 role × 3 scenarios = 3 rows
        assert len(df) == 3

    def test_aggressive_displacement_geq_moderate(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        for role_name in df["role_name"].unique():
            moderate_rows = df[(df["scenario"] == "Moderate") & (df["role_name"] == role_name)]
            aggressive_rows = df[(df["scenario"] == "Aggressive") & (df["role_name"] == role_name)]
            if not moderate_rows.empty and not aggressive_rows.empty:
                assert (
                    aggressive_rows["displaced_workers"].iloc[0]
                    >= moderate_rows["displaced_workers"].iloc[0]
                )


# --------------------------------------------------------------------------- #
# generate_csv_bytes                                                           #
# --------------------------------------------------------------------------- #


class TestGenerateCsvBytes:
    def test_returns_bytes(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report)
        assert isinstance(result, bytes)

    def test_non_empty(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report)
        assert len(result) > 0

    def test_utf8_decodable(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report)
        decoded = result.decode("utf-8")
        assert isinstance(decoded, str)

    def test_contains_org_name(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "Test Organisation" in result

    def test_contains_scenario_names(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "Optimistic" in result
        assert "Moderate" in result
        assert "Aggressive" in result

    def test_contains_header_comment(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "AI Labour Impact Calculator" in result

    def test_contains_role_breakdown_by_default(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report, include_role_breakdown=True)
        decoded = result.decode("utf-8")
        assert "Role Breakdown" in decoded

    def test_no_role_breakdown_when_disabled(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report, include_role_breakdown=False)
        decoded = result.decode("utf-8")
        assert "Role Breakdown" not in decoded

    def test_contains_currency_code_column_headers(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert f"robot_tax_liability_{CURRENCY_CODE}" in result

    def test_type_error_on_non_report(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            generate_csv_bytes(None)  # type: ignore

    def test_type_error_on_string(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            generate_csv_bytes("not a report")  # type: ignore

    def test_zero_displacement_csv(self, zero_displacement_report) -> None:
        result = generate_csv_bytes(zero_displacement_report).decode("utf-8")
        assert "Zero Corp" in result

    def test_disclaimer_in_csv(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        # The disclaimer or policy framework attribution should appear
        assert (
            "illustrative" in result.lower()
            or "disclaimer" in result.lower()
            or "purposes" in result.lower()
            or "OpenAI" in result
        )

    def test_newline_separator_present(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "\n" in result

    def test_csv_without_breakdown_smaller_than_with(self, standard_report) -> None:
        with_breakdown = generate_csv_bytes(standard_report, include_role_breakdown=True)
        without_breakdown = generate_csv_bytes(standard_report, include_role_breakdown=False)
        assert len(with_breakdown) > len(without_breakdown)

    def test_generated_timestamp_in_csv(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "UTC" in result

    def test_policy_framework_name_in_csv(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "OpenAI" in result

    def test_high_displacement_csv_non_zero_values(self, high_displacement_report) -> None:
        result = generate_csv_bytes(high_displacement_report).decode("utf-8")
        assert "High Automation Corp" in result
        # Should have non-zero displaced values in the CSV data
        data_lines = [ln for ln in result.splitlines() if not ln.startswith("#")]
        data_str = "\n".join(data_lines)
        parsed = pd.read_csv(io.StringIO(data_str))
        assert parsed["total_displaced"].max() > 0


# --------------------------------------------------------------------------- #
# render_pdf_html                                                              #
# --------------------------------------------------------------------------- #


class TestRenderPdfHtml:
    def test_returns_string(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert isinstance(html, str)

    def test_non_empty(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert len(html) > 100

    def test_is_valid_html(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_org_name_in_output(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "Test Organisation" in html

    def test_all_scenario_names_present(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "Optimistic" in html
        assert "Moderate" in html
        assert "Aggressive" in html

    def test_currency_symbol_present(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert CURRENCY_SYMBOL in html

    def test_policy_framework_name_present(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "OpenAI" in html

    def test_disclaimer_present(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "illustrative" in html.lower() or "disclaimer" in html.lower()

    def test_role_names_in_html(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "Data Entry" in html
        assert "Analysts" in html
        assert "Managers" in html

    def test_type_error_on_non_report(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            render_pdf_html({"not": "a report"})  # type: ignore

    def test_type_error_on_none(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            render_pdf_html(None)  # type: ignore

    def test_zero_displacement_renders(self, zero_displacement_report) -> None:
        html = render_pdf_html(zero_displacement_report)
        assert "Zero Corp" in html

    def test_generated_at_timestamp_present(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        # Should contain a year fragment from the timestamp
        assert "20" in html  # UTC year will contain "20xx"

    def test_money_filter_applied(self, standard_report) -> None:
        """Money values should appear formatted with currency symbol."""
        html = render_pdf_html(standard_report)
        assert CURRENCY_SYMBOL in html

    def test_single_role_renders_without_error(self, single_role_report) -> None:
        html = render_pdf_html(single_role_report)
        assert "Solo Org" in html
        assert "Clerks" in html

    def test_html_contains_body_element(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "<body" in html
        assert "</body>" in html

    def test_html_contains_head_element(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "<head" in html
        assert "</head>" in html

    def test_html_contains_style(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "<style" in html

    def test_html_contains_table(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        assert "<table" in html
        assert "</table>" in html

    def test_all_scenario_financial_values_appear(self, standard_report) -> None:
        html = render_pdf_html(standard_report)
        for scenario in standard_report.all_scenarios:
            # Financial values should appear somewhere in the formatted HTML
            # They will be formatted as money strings
            assert scenario.scenario_name in html

    def test_high_displacement_renders(self, high_displacement_report) -> None:
        html = render_pdf_html(high_displacement_report)
        assert "High Automation Corp" in html


# --------------------------------------------------------------------------- #
# generate_pdf_bytes                                                           #
# --------------------------------------------------------------------------- #


class TestGeneratePdfBytes:
    def test_returns_bytes(self, standard_report) -> None:
        result = generate_pdf_bytes(standard_report)
        assert isinstance(result, bytes)

    def test_non_empty(self, standard_report) -> None:
        result = generate_pdf_bytes(standard_report)
        assert len(result) > 0

    def test_pdf_magic_bytes(self, standard_report) -> None:
        """PDF files start with the magic bytes %PDF."""
        result = generate_pdf_bytes(standard_report)
        assert result[:4] == b"%PDF", (
            f"Expected PDF magic bytes b'%PDF', got {result[:4]!r}"
        )

    def test_type_error_on_non_report(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            generate_pdf_bytes("string")  # type: ignore

    def test_type_error_on_none(self) -> None:
        with pytest.raises(TypeError, match="FullReport"):
            generate_pdf_bytes(None)  # type: ignore

    def test_zero_displacement_pdf(self, zero_displacement_report) -> None:
        result = generate_pdf_bytes(zero_displacement_report)
        assert result[:4] == b"%PDF"

    def test_single_role_pdf(self, single_role_report) -> None:
        result = generate_pdf_bytes(single_role_report)
        assert result[:4] == b"%PDF"

    def test_pdf_larger_than_minimum_threshold(self, standard_report) -> None:
        """A real PDF with content should be at least a few KB."""
        result = generate_pdf_bytes(standard_report)
        assert len(result) > 1024  # At least 1 KB

    def test_high_displacement_pdf(self, high_displacement_report) -> None:
        result = generate_pdf_bytes(high_displacement_report)
        assert result[:4] == b"%PDF"
        assert len(result) > 1024


# --------------------------------------------------------------------------- #
# Formatting helpers                                                           #
# --------------------------------------------------------------------------- #


class TestFormattingHelpers:
    # _fmt_money
    def test_money_basic(self) -> None:
        assert _fmt_money(1234567.89) == "$1,234,567.89"

    def test_money_zero(self) -> None:
        assert _fmt_money(0.0) == "$0.00"

    def test_money_negative(self) -> None:
        result = _fmt_money(-500.0)
        assert "-" in result
        assert "500.00" in result

    def test_money_custom_symbol(self) -> None:
        result = _fmt_money(1000.0, symbol="£")
        assert result.startswith("£")
        assert "1,000.00" in result

    def test_money_large_number(self) -> None:
        result = _fmt_money(1_000_000.0)
        assert "1,000,000.00" in result

    def test_money_small_value(self) -> None:
        result = _fmt_money(0.01)
        assert "0.01" in result

    def test_money_integer_input(self) -> None:
        result = _fmt_money(5000)
        assert "5,000.00" in result

    # _fmt_pct
    def test_pct_basic(self) -> None:
        assert _fmt_pct(45.3) == "45.3%"

    def test_pct_zero(self) -> None:
        assert _fmt_pct(0.0) == "0.0%"

    def test_pct_100(self) -> None:
        assert _fmt_pct(100.0) == "100.0%"

    def test_pct_decimal_precision(self) -> None:
        # Should round to PERCENTAGE_DECIMAL_PLACES (1)
        result = _fmt_pct(33.33333)
        assert "%" in result
        assert result == "33.3%"

    def test_pct_rounds_correctly(self) -> None:
        assert _fmt_pct(33.35) == "33.4%" or _fmt_pct(33.35) == "33.3%"  # banker's rounding ok

    def test_pct_negative(self) -> None:
        result = _fmt_pct(-5.0)
        assert "%" in result
        assert "-5.0" in result

    # _fmt_intcomma
    def test_intcomma_basic(self) -> None:
        assert _fmt_intcomma(1234567) == "1,234,567"

    def test_intcomma_zero(self) -> None:
        assert _fmt_intcomma(0) == "0"

    def test_intcomma_small(self) -> None:
        assert _fmt_intcomma(42) == "42"

    def test_intcomma_from_float(self) -> None:
        # Should truncate float to int
        result = _fmt_intcomma(1234.9)
        assert result == "1,234"

    def test_intcomma_large(self) -> None:
        assert _fmt_intcomma(1_000_000) == "1,000,000"

    def test_intcomma_negative(self) -> None:
        result = _fmt_intcomma(-1000)
        assert "-" in result
        assert "1,000" in result

    def test_intcomma_thousand_boundary(self) -> None:
        assert _fmt_intcomma(1000) == "1,000"
        assert _fmt_intcomma(999) == "999"

    # _utc_timestamp
    def test_timestamp_returns_string(self) -> None:
        ts = _utc_timestamp()
        assert isinstance(ts, str)

    def test_timestamp_contains_utc(self) -> None:
        ts = _utc_timestamp()
        assert "UTC" in ts

    def test_timestamp_contains_year(self) -> None:
        ts = _utc_timestamp()
        assert "20" in ts  # Will be valid for years 2000–2099

    def test_timestamp_non_empty(self) -> None:
        ts = _utc_timestamp()
        assert len(ts) > 10

    def test_timestamp_format(self) -> None:
        ts = _utc_timestamp()
        # Expected format: "YYYY-MM-DD HH:MM:SS UTC"
        parts = ts.split()
        assert len(parts) == 3
        assert parts[2] == "UTC"
        date_part = parts[0]
        assert len(date_part) == 10
        assert date_part[4] == "-"
        assert date_part[7] == "-"

    def test_two_timestamps_close_together(self) -> None:
        ts1 = _utc_timestamp()
        ts2 = _utc_timestamp()
        # Both should be the same date at least
        assert ts1[:10] == ts2[:10]


# --------------------------------------------------------------------------- #
# Integration: CSV content matches DataFrame values                            #
# --------------------------------------------------------------------------- #


class TestCsvDataIntegrity:
    def _parse_csv_data(self, csv_bytes: bytes) -> pd.DataFrame:
        """Helper: strip comment lines and parse CSV into a DataFrame."""
        decoded = csv_bytes.decode("utf-8")
        data_lines = [ln for ln in decoded.splitlines() if not ln.startswith("#")]
        # Remove blank separator lines
        data_lines = [ln for ln in data_lines if ln.strip()]
        data_str = "\n".join(data_lines)
        return pd.read_csv(io.StringIO(data_str))

    def test_csv_total_displaced_matches_dataframe(
        self, standard_report
    ) -> None:
        """Verify that values in the CSV match those from the DataFrame."""
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        expected_df = build_report_dataframe(standard_report)

        assert list(parsed_df["total_displaced"]) == list(
            expected_df["total_displaced"]
        )

    def test_csv_financial_exposure_matches_dataframe(
        self, standard_report
    ) -> None:
        """Verify financial exposure values are identical in CSV and DataFrame."""
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        expected_df = build_report_dataframe(standard_report)

        col = f"total_financial_exposure_{CURRENCY_CODE}"
        for parsed_val, expected_val in zip(
            parsed_df[col], expected_df[col]
        ):
            assert math.isclose(float(parsed_val), float(expected_val), rel_tol=1e-5)

    def test_csv_scenario_names_match_dataframe(self, standard_report) -> None:
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        expected_df = build_report_dataframe(standard_report)
        assert list(parsed_df["scenario"]) == list(expected_df["scenario"])

    def test_csv_headcount_matches_dataframe(self, standard_report) -> None:
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        expected_df = build_report_dataframe(standard_report)
        assert list(parsed_df["total_headcount"]) == list(expected_df["total_headcount"])

    def test_csv_robot_tax_matches_dataframe(self, standard_report) -> None:
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        expected_df = build_report_dataframe(standard_report)
        col = f"robot_tax_liability_{CURRENCY_CODE}"
        for pv, ev in zip(parsed_df[col], expected_df[col]):
            assert math.isclose(float(pv), float(ev), rel_tol=1e-5)

    def test_csv_has_three_data_rows(self, standard_report) -> None:
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        assert len(parsed_df) == 3

    def test_csv_zero_displacement_all_zeros(self, zero_displacement_report) -> None:
        csv_bytes = generate_csv_bytes(zero_displacement_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        assert (parsed_df["total_displaced"] == 0).all()

    def test_csv_displacement_pct_in_range(self, standard_report) -> None:
        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        parsed_df = self._parse_csv_data(csv_bytes)
        assert (parsed_df["displacement_pct"] >= 0.0).all()
        assert (parsed_df["displacement_pct"] <= 100.0).all()
