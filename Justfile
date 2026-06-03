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

# Bump version and cut a GitHub release: just release patch|minor|major
release bump:
    #!/usr/bin/env bash
    set -euo pipefail
    old=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')
    IFS='.' read -r major minor patch <<< "$old"
    case "{{ bump }}" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) echo "Usage: just release patch|minor|major"; exit 1 ;;
    esac
    new="${major}.${minor}.${patch}"
    sed -i '' "s/^version = \"${old}\"/version = \"${new}\"/" pyproject.toml
    git add pyproject.toml
    git commit -m "chore: bump version from ${old} to ${new}"
    git tag "v${new}"
    git push && git push --tags
    gh release create "v${new}" --title "v${new}" --generate-notes
