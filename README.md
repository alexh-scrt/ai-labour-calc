# AI Labour Impact Calculator

> Model AI-driven workforce disruption before it models you.

The AI Labour Impact Calculator is a web tool for businesses and policy researchers to quantify projected AI-driven workforce changes across **three automation timelines** — optimistic, moderate, and aggressive. Enter your organisation's headcount, role categories, and automation potential to instantly generate a scenario comparison covering job displacement, robot tax liabilities, and social safety-net cost exposure. All projections are grounded in OpenAI's proposed industrial policy framework.

---

## Quick Start

**Requirements:** Python 3.11+, and [WeasyPrint system dependencies](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for PDF export.

```bash
# 1. Clone the repository
git clone https://github.com/your-org/ai_labour_calc.git
cd ai_labour_calc

# 2. Install dependencies (pip)
pip install -e .

# — or with uv —
uv pip install -e .

# 3. Run the development server
flask --app ai_labour_calc run
```

Open [http://localhost:5000](http://localhost:5000) in your browser, fill in your organisation details and role data, and click **Calculate** to see your scenario report.

---

## Features

- **Three-scenario automation modelling** — Compare optimistic, moderate, and aggressive AI adoption timelines side-by-side with configurable, role-level automation potential percentages.
- **Robot tax liability estimation** — Progressive tax rate schedules applied to displaced worker counts and average salaries, based on OpenAI's proposed policy framework.
- **Social safety-net cost exposure** — Calculates retraining costs, UBI-style transfer projections, and unemployment insurance exposure per scenario.
- **Interactive Chart.js visualisations** — Bar and line charts comparing workforce displacement and total financial exposure across all three timelines.
- **Downloadable reports** — Export your full scenario comparison as a styled PDF or a flat CSV for spreadsheet analysis.

---

## Usage Examples

### Web Interface

1. Navigate to `http://localhost:5000`.
2. Enter your **organisation name** and **average annual salary**.
3. Add one or more **role categories** — provide a role name, headcount, and estimated automation potential (0–100%).
4. Click **Calculate Scenarios**.
5. Review the three-scenario comparison table and interactive charts on the results page.
6. Download your report via the **Export CSV** or **Download PDF** buttons.

### Programmatic Usage

You can use the calculation engine and report generator directly in Python:

```python
from ai_labour_calc.models import RoleInput
from ai_labour_calc.calculator import calculate_report
from ai_labour_calc.report import generate_csv_bytes, generate_pdf_bytes

# Define your workforce roles
roles = [
    RoleInput(name="Data Entry Clerks",   headcount=120, automation_potential=85.0),
    RoleInput(name="Customer Support",     headcount=80,  automation_potential=60.0),
    RoleInput(name="Software Engineers",   headcount=45,  automation_potential=25.0),
]

# Run the three-scenario calculation
report = calculate_report(
    roles=roles,
    average_annual_salary=62_000.0,
    organisation_name="Acme Corp"
)

# Inspect scenario results
for scenario in [report.optimistic, report.moderate, report.aggressive]:
    print(f"{scenario.label}: {scenario.total_displaced} displaced, "
          f"robot tax ${scenario.robot_tax_liability:,.0f}")

# Export to CSV
csv_data = generate_csv_bytes(report)
with open("acme_report.csv", "wb") as f:
    f.write(csv_data)

# Export to PDF
pdf_data = generate_pdf_bytes(report)
with open("acme_report.pdf", "wb") as f:
    f.write(pdf_data)
```

### Example CLI (via Flask shell)

```bash
flask --app ai_labour_calc shell

>>> from ai_labour_calc.models import RoleInput
>>> from ai_labour_calc.calculator import calculate_report
>>> roles = [RoleInput("Analysts", 50, 70.0)]
>>> r = calculate_report(roles, 75000.0, "Research Ltd")
>>> r.moderate.total_displaced
28
>>> r.moderate.robot_tax_liability
1470000.0
```

---

## Project Structure

```
ai_labour_calc/
├── pyproject.toml                        # Project metadata, dependencies, build config
├── README.md                             # This file
│
├── ai_labour_calc/
│   ├── __init__.py                       # Flask application factory (create_app)
│   ├── app.py                            # Routes: form input, calculate, results, CSV/PDF download
│   ├── calculator.py                     # Core scenario calculation engine
│   ├── models.py                         # Dataclasses: RoleInput, ScenarioResult, FullReport
│   ├── report.py                         # CSV and PDF report generation
│   ├── assumptions.py                    # Centralised policy constants and rate schedules
│   │
│   ├── templates/
│   │   ├── index.html                    # Input form (headcount, roles, automation potential)
│   │   ├── results.html                  # Results dashboard with Chart.js visualisations
│   │   └── report_pdf.html               # Print-optimised template for WeasyPrint PDF
│   │
│   └── static/
│       └── style.css                     # Responsive stylesheet for form and results pages
│
└── tests/
    ├── __init__.py
    ├── test_calculator.py                # Unit tests for calculation engine
    └── test_report.py                    # Tests for CSV and PDF report generation
```

---

## Configuration

All policy parameters, tax rate schedules, timeline multipliers, and safety-net cost assumptions live in **`ai_labour_calc/assumptions.py`**. Editing this file propagates changes throughout the entire application without touching calculation logic.

| Constant | Description | Default |
|---|---|---|
| `SCENARIOS` | Ordered list of timeline labels | `["optimistic", "moderate", "aggressive"]` |
| `TIMELINE_MULTIPLIERS` | Displacement scaling factor per scenario | `{optimistic: 0.5, moderate: 0.75, aggressive: 1.0}` |
| `ROBOT_TAX_RATE` | Progressive rate schedule tiers | See `assumptions.py` |
| `RETRAINING_COST_PER_WORKER` | Estimated retraining cost per displaced worker | `$15,000` |
| `UBI_ANNUAL_TRANSFER` | Annual UBI-style transfer per displaced worker | `$12,000` |
| `MAX_DISPLACEMENT_RATE` | Upper cap on effective displacement rate | `0.95` |

To adapt the tool for a specific jurisdiction or research scenario, update the relevant constants in `assumptions.py` before running the application.

**Environment variables** (optional):

```bash
# Set a custom Flask secret key (recommended for production)
export SECRET_KEY="your-secret-key-here"

# Enable debug mode
export FLASK_DEBUG=1
```

---

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run the full test suite
pytest

# With coverage report
pytest --cov=ai_labour_calc --cov-report=term-missing
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Built with [Jitter](https://github.com/jitter-ai) — an AI agent that ships code daily.*
