"""Test suite for the AI Labour Impact Calculator.

This package contains all pytest-based unit and integration tests for the
``ai_labour_calc`` package. Tests are organised into modules mirroring
the source package structure:

- ``test_calculator.py`` — Unit tests for the core calculation engine
  (scenario computation, displacement, robot tax, safety-net exposure)
- ``test_report.py`` — Tests for CSV and PDF report generation,
  validating output structure, column presence, and content correctness

All tests use pytest conventions: test functions are prefixed with
``test_``, fixtures are defined at module or package level as needed,
and assertions use plain ``assert`` statements.

Running the full test suite::

    pytest

With coverage::

    pytest --cov=ai_labour_calc --cov-report=term-missing
"""
