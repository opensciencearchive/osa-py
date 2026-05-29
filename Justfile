default:
    @just --list

# Run all checks (lint, typecheck, test)
check: lint test

# Run tests
test *args:
    uv run pytest tests/ -v --tb=short {{ args }}

# Run tests with coverage
coverage:
    uv run pytest tests/ --cov=osa --cov-report=term-missing

# Lint and format check
lint:
    uv run ruff check osa/ tests/
    uv run ruff format --check osa/ tests/
    uv run ty check osa

# Auto-fix lint errors and format
fix:
    uv run ruff check osa/ tests/ --fix
    uv run ruff format osa/ tests/

# Build the package
build:
    uv build

# Clean build artifacts
clean:
    rm -rf dist/ build/ *.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Install in development mode
dev:
    uv sync
