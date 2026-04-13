# AI Labour Impact Calculator

A web tool for businesses and policy researchers to model projected AI-driven workforce changes across **three automation timelines** — optimistic, moderate, and aggressive — grounded in OpenAI's proposed industrial policy framework.

## Features

- **Three-scenario modelling** — Compare optimistic, moderate, and aggressive AI automation timelines side-by-side
- **Role-level automation potential** — Input your organisation's headcount and per-role automation potential percentages
- **Robot tax liability estimation** — Calculate projected robot tax obligations based on displaced worker count, average salary, and proposed tax rate schedules
- **Social safety-net cost exposure** — Model retraining costs, UBI-style transfers, and unemployment insurance projections
- **Interactive charts** — Chart.js visualisations comparing workforce displacement and financial exposure across all three scenarios
- **Downloadable reports** — Export results as styled PDF or raw CSV for further analysis

## Requirements

- Python 3.11 or later
- pip / [uv](https://github.com/astral-sh/uv) package manager

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-org/ai_labour_calc.git
cd ai_labour_calc
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

> **Note for WeasyPrint:** WeasyPrint requires system-level libraries (`pango`, `cairo`, `gdk-pixbuf`). See the [WeasyPrint installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for platform-specific instructions.

**macOS (Homebrew):**
```bash
brew install pango cairo gdk-pixbuf libffi
```

**Ubuntu/Debian:**
```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0 libcairo2
```

## Running the Application

```bash
# Development server
flask --app ai_labour_calc run --debug

# Or using the installed script
ai-labour-calc
```

The application will be available at [http://localhost:5000](http://localhost:5000).

## Usage Guide

### Step 1 — Enter Organisation Details

On the home page, provide:
- **Organisation name** — used in report headers
- **Average annual salary** — baseline for robot tax and safety-net calculations
- **Role categories** — add one or more role types with:
  - Role name
  - Number of workers in that role
  - Estimated automation potential (0–100%)

### Step 2 — View Results

The results page shows a side-by-side comparison of all three scenarios including:
- Projected job displacement (headcount and percentage)
- Estimated annual robot tax liability
- Social safety-net cost exposure (retraining + transfers + UI)
- Interactive bar and line charts

### Step 3 — Download Reports

- **Download CSV** — Raw scenario data as a spreadsheet-ready CSV
- **Download PDF** — Formatted report with charts and narrative summary

## Running Tests

```bash
pytest

# With coverage report
pytest --cov=ai_labour_calc --cov-report=term-missing
```

## Project Structure

```
ai_labour_calc/
├── __init__.py          # Flask app factory
├── app.py               # Routes and view functions
├── calculator.py        # Core scenario calculation engine
├── models.py            # Dataclasses: RoleInput, ScenarioResult, FullReport
├── report.py            # CSV and PDF report generation
├── assumptions.py       # Tax rates, timelines, policy parameters
├── static/
│   └── style.css        # Responsive stylesheet
└── templates/
    ├── index.html       # Input form
    ├── results.html     # Results dashboard
    └── report_pdf.html  # Print-optimised PDF template
tests/
├── __init__.py
├── test_calculator.py   # Calculator unit tests
└── test_report.py       # Report generation tests
pyproject.toml
README.md
```

## Assumptions and Policy Framework

All calculations are based on parameters in `ai_labour_calc/assumptions.py`, which can be adjusted to reflect different policy environments:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Robot tax rate (base) | 10% | Percentage of displaced worker annual salary |
| Timeline multipliers | 0.5 / 1.0 / 1.5 | Optimistic / Moderate / Aggressive |
| Retraining cost per worker | $15,000 | One-time retraining program cost |
| UBI-style monthly transfer | $1,000/month | Annual per-displaced-worker transfer |
| Unemployment insurance | 6 months salary | Average UI duration assumption |

> These values are illustrative and grounded in OpenAI's proposed industrial policy framework. Adjust them to match your jurisdiction and scenario assumptions.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

## License

MIT License — see [LICENSE](LICENSE) for details.
