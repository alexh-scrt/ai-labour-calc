"""Data models for the AI Labour Impact Calculator.

This module defines all dataclasses used throughout the application to
represent user inputs, per-scenario calculation results, and the full
aggregated report structure.

Structure::

    RoleInput          — a single role category entered by the user
    ScenarioResult     — calculated outputs for one automation timeline
    FullReport         — aggregates all three scenarios plus metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class RoleInput:
    """Represents a single role category provided by the user.

    Attributes:
        role_name: Human-readable label for the role category
            (e.g. "Data Entry Clerks", "Customer Service Agents").
        headcount: Number of workers currently in this role. Must be
            a non-negative integer.
        automation_potential: Estimated percentage of work in this role
            that could be automated, expressed as a value between 0.0
            and 100.0 inclusive.

    Example::

        role = RoleInput(
            role_name="Data Entry Clerks",
            headcount=120,
            automation_potential=85.0,
        )
    """

    role_name: str
    headcount: int
    automation_potential: float  # 0.0 – 100.0 percent

    def __post_init__(self) -> None:
        """Validate field values after initialisation.

        Raises:
            ValueError: If ``headcount`` is negative or
                ``automation_potential`` is outside [0, 100].
            TypeError: If field types are incompatible.
        """
        if not isinstance(self.role_name, str) or not self.role_name.strip():
            raise ValueError("role_name must be a non-empty string.")
        if self.headcount < 0:
            raise ValueError(
                f"headcount must be non-negative, got {self.headcount}."
            )
        if not (0.0 <= self.automation_potential <= 100.0):
            raise ValueError(
                "automation_potential must be between 0 and 100, "
                f"got {self.automation_potential}."
            )


@dataclass
class RoleDisplacement:
    """Displacement breakdown for a single role within one scenario.

    Attributes:
        role_name: Name of the role category.
        original_headcount: Starting headcount before displacement.
        displaced_workers: Number of workers projected to be displaced.
        remaining_workers: Headcount projected to remain post-displacement.
        displacement_rate: Actual fractional displacement rate applied
            (0.0 – 1.0) after multiplying automation potential by the
            scenario timeline multiplier (capped at 1.0).
    """

    role_name: str
    original_headcount: int
    displaced_workers: int
    remaining_workers: int
    displacement_rate: float  # 0.0 – 1.0


@dataclass
class ScenarioResult:
    """Calculated outputs for a single automation timeline scenario.

    This dataclass captures every financial and workforce metric
    produced by the calculation engine for one scenario (optimistic,
    moderate, or aggressive).

    Attributes:
        scenario_name: Display name for the scenario
            (``"Optimistic"``, ``"Moderate"``, or ``"Aggressive"``).
        timeline_years: Number of years over which the automation is
            projected to unfold.
        timeline_multiplier: Scalar applied to each role's raw automation
            potential to derive the effective displacement rate.
        total_headcount: Total workers across all role inputs.
        total_displaced: Total projected number of displaced workers.
        total_remaining: Total workers projected to remain.
        displacement_percentage: ``total_displaced / total_headcount * 100``
            (0.0 if total_headcount is zero).
        robot_tax_liability: Estimated annual robot tax owed by the
            organisation, in the same currency as ``average_annual_salary``.
        retraining_cost: Total one-time retraining programme cost for
            all displaced workers.
        ubi_transfer_annual: Annual UBI-style transfer obligation for
            displaced workers.
        unemployment_insurance_cost: Estimated UI cost based on average
            salary and duration assumption.
        total_safety_net_exposure: Sum of ``retraining_cost``,
            ``ubi_transfer_annual``, and ``unemployment_insurance_cost``.
        role_breakdowns: Per-role displacement detail records.
    """

    scenario_name: str
    timeline_years: int
    timeline_multiplier: float

    total_headcount: int
    total_displaced: int
    total_remaining: int
    displacement_percentage: float

    robot_tax_liability: float
    retraining_cost: float
    ubi_transfer_annual: float
    unemployment_insurance_cost: float
    total_safety_net_exposure: float

    role_breakdowns: List[RoleDisplacement] = field(default_factory=list)

    @property
    def total_financial_exposure(self) -> float:
        """Combined robot tax liability and safety-net exposure.

        Returns:
            The sum of ``robot_tax_liability`` and
            ``total_safety_net_exposure``.
        """
        return self.robot_tax_liability + self.total_safety_net_exposure


@dataclass
class FullReport:
    """Aggregated report combining all three automation scenarios.

    This is the top-level data structure returned by the calculation
    engine and consumed by the report generation and templating layers.

    Attributes:
        organisation_name: Name of the organisation submitting the
            analysis, used in report headers.
        average_annual_salary: Baseline annual salary (in the user's
            chosen currency) used across all financial calculations.
        roles: Original list of :class:`RoleInput` objects provided by
            the user.
        optimistic: :class:`ScenarioResult` for the optimistic timeline.
        moderate: :class:`ScenarioResult` for the moderate timeline.
        aggressive: :class:`ScenarioResult` for the aggressive timeline.

    Example::

        report = FullReport(
            organisation_name="Acme Corp",
            average_annual_salary=55000.0,
            roles=[...],
            optimistic=...,
            moderate=...,
            aggressive=...,
        )
        all_scenarios = report.all_scenarios
    """

    organisation_name: str
    average_annual_salary: float
    roles: List[RoleInput]
    optimistic: ScenarioResult
    moderate: ScenarioResult
    aggressive: ScenarioResult

    @property
    def all_scenarios(self) -> List[ScenarioResult]:
        """Return all three scenarios in order: optimistic, moderate, aggressive.

        Returns:
            A list of :class:`ScenarioResult` objects ordered from least
            to most aggressive automation timeline.
        """
        return [self.optimistic, self.moderate, self.aggressive]

    @property
    def total_headcount(self) -> int:
        """Total worker headcount across all role inputs.

        This value is the same in every scenario (only displacement
        numbers vary), so it is derived from the optimistic scenario.

        Returns:
            Total headcount as an integer.
        """
        return self.optimistic.total_headcount

    @property
    def max_displaced(self) -> int:
        """Maximum displaced worker count across all three scenarios.

        Useful for scaling chart axes to the worst-case scenario.

        Returns:
            Integer count of displaced workers in the most aggressive
            scenario.
        """
        return max(s.total_displaced for s in self.all_scenarios)

    @property
    def max_financial_exposure(self) -> float:
        """Maximum combined financial exposure across all three scenarios.

        Returns:
            Highest ``total_financial_exposure`` value among all scenarios.
        """
        return max(s.total_financial_exposure for s in self.all_scenarios)
