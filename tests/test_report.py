"""Tests for CSV and PDF report generation.

Covers:
- build_report_dataframe: shape, columns, values, type errors
- build_role_breakdown_dataframe: shape, columns, values
- generate_csv_bytes: encoding, content structure, headers
- render_pdf_html: returns string, contains key content
- generate_pdf_bytes: returns bytes, non-empty, PDF magic bytes
- _fmt_money, _fmt_pct, _fmt_intcomma: formatting helpers
- Edge cases: zero headcount, zero displacement, single role
"""

from __future__ import annotations

import math
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


# --------------------------------------------------------------------------- #
# build_report_dataframe                                                       #
# --------------------------------------------------------------------------- #


class TestBuildReportDataframe:
    def test_returns_dataframe_with_three_rows(self, standard_report) -> None:
        df = build_report_dataframe(standard_report)
        assert len(df) == 3

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

    def test_zero_automation_all_zeros(self, zero_displacement_report) -> None:
        df = build_role_breakdown_dataframe(zero_displacement_report)
        assert (df["displaced_workers"] == 0).all()
        assert (df["displacement_rate"] == 0.0).all()

    def test_organisation_column_populated(self, standard_report) -> None:
        df = build_role_breakdown_dataframe(standard_report)
        assert all(df["organisation"] == "Test Organisation")


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

    def test_zero_displacement_csv(self, zero_displacement_report) -> None:
        result = generate_csv_bytes(zero_displacement_report).decode("utf-8")
        assert "Zero Corp" in result

    def test_disclaimer_in_csv(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "illustrative" in result.lower() or "disclaimer" in result.lower() or "purposes" in result.lower()

    def test_newline_separator_present(self, standard_report) -> None:
        result = generate_csv_bytes(standard_report).decode("utf-8")
        assert "\n" in result


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


# --------------------------------------------------------------------------- #
# Integration: CSV content matches DataFrame values                            #
# --------------------------------------------------------------------------- #


class TestCsvDataIntegrity:
    def test_csv_total_displaced_matches_dataframe(
        self, standard_report
    ) -> None:
        """Verify that values in the CSV match those from the DataFrame."""
        import io
        import pandas as pd

        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        decoded = csv_bytes.decode("utf-8")

        # Strip comment lines beginning with '#'
        data_lines = [ln for ln in decoded.splitlines() if not ln.startswith("#")]
        data_str = "\n".join(data_lines)

        parsed_df = pd.read_csv(io.StringIO(data_str))

        expected_df = build_report_dataframe(standard_report)

        # Check displaced worker counts match
        assert list(parsed_df["total_displaced"]) == list(
            expected_df["total_displaced"]
        )

    def test_csv_financial_exposure_matches_dataframe(
        self, standard_report
    ) -> None:
        """Verify financial exposure values are identical in CSV and DataFrame."""
        import io
        import pandas as pd

        csv_bytes = generate_csv_bytes(standard_report, include_role_breakdown=False)
        decoded = csv_bytes.decode("utf-8")

        data_lines = [ln for ln in decoded.splitlines() if not ln.startswith("#")]
        data_str = "\n".join(data_lines)

        parsed_df = pd.read_csv(io.StringIO(data_str))
        expected_df = build_report_dataframe(standard_report)

        col = f"total_financial_exposure_{CURRENCY_CODE}"
        for parsed_val, expected_val in zip(
            parsed_df[col], expected_df[col]
        ):
            assert math.isclose(float(parsed_val), float(expected_val), rel_tol=1e-5)
