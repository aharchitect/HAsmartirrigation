# Smart Irrigation Development Makefile

.PHONY: help setup test test-e2e test-e2e-debug lint format clean install-dev frontend-e2e exploratory-setup exploratory-up exploratory-logs exploratory-shell exploratory-down exploratory-reset

E2E_VENV := .venv-e2e
E2E_PYTHON := $(E2E_VENV)/bin/python
E2E_INSTALLED := $(E2E_VENV)/.requirements-installed
FRONTEND_DIR := custom_components/smart_irrigation/frontend

# Default target
help:
	@echo "Smart Irrigation Development Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  setup       - Create virtual environment and install dependencies"
	@echo "  install-dev - Install development dependencies (assumes .venv exists)"
	@echo ""
	@echo "Testing:"
	@echo "  test        - Run all tests"
	@echo "  test-e2e    - Build the frontend and run Docker-backed HA runtime tests"
	@echo "  test-e2e-debug - Run E2E tests and retain sanitized artifacts"
	@echo "  exploratory-setup - Prepare and start the persistent exploratory HA stack"
	@echo "  exploratory-up - Start the prepared exploratory HA stack"
	@echo "  exploratory-logs - Follow exploratory HA and mock logs"
	@echo "  exploratory-shell - Open a shell in exploratory Home Assistant"
	@echo "  exploratory-down - Stop the exploratory stack and preserve state"
	@echo "  exploratory-reset - Delete exploratory state (requires FORCE=1)"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint        - Run linting (ruff)"
	@echo "  format      - Format code (black)"
	@echo "  check       - Run all CI checks (lint + format)"
	@echo ""
	@echo "Utilities:"
	@echo "  clean       - Remove virtual environment and cache files"

# Setup virtual environment with Python 3.14 (matches GitHub Actions and the
# current Home Assistant test stack).
setup:
	@echo "Setting up Smart Irrigation development environment..."
	@which python3.14 > /dev/null || (echo "❌ Python 3.14 not found. Install it first." && exit 1)
	python3.14 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements-dev.txt
	@echo ""
	@echo "✅ Setup complete! Activate with: source .venv/bin/activate"
	@./.venv/bin/python --version

# Install development dependencies (assumes venv exists)
install-dev:
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements-dev.txt

# Run the same test set as GitHub Actions
test:
	./.venv/bin/python -m pytest

$(E2E_INSTALLED): requirements.e2e.txt
	python3.14 -m venv $(E2E_VENV)
	$(E2E_PYTHON) -m pip install --upgrade pip
	$(E2E_PYTHON) -m pip install -r requirements.e2e.txt
	@touch $(E2E_INSTALLED)

frontend-e2e:
	npm ci --legacy-peer-deps --prefix $(FRONTEND_DIR)
	npm run build --prefix $(FRONTEND_DIR)

test-e2e: frontend-e2e $(E2E_INSTALLED)
	$(E2E_PYTHON) -m pytest -c tests_e2e/pytest.ini -p no:cacheprovider tests_e2e/

test-e2e-debug: frontend-e2e $(E2E_INSTALLED)
	E2E_KEEP_ARTIFACTS=1 $(E2E_PYTHON) -m pytest -c tests_e2e/pytest.ini -p no:cacheprovider tests_e2e/ -s

exploratory-setup:
	./.venv/bin/python scripts/exploratory_commands.py setup

exploratory-up:
	./.venv/bin/python scripts/exploratory_commands.py up

exploratory-logs:
	./.venv/bin/python scripts/exploratory_commands.py logs

exploratory-shell:
	./.venv/bin/python scripts/exploratory_commands.py shell

exploratory-down:
	./.venv/bin/python scripts/exploratory_commands.py down

exploratory-reset:
	./.venv/bin/python scripts/exploratory_commands.py reset

# Code formatting (matches CI requirements)
format: install-dev
	./.venv/bin/black .
	@echo "✅ Code formatted"

# Linting (matches CI requirements)
lint: install-dev
	./.venv/bin/ruff check custom_components/smart_irrigation/
	@echo "✅ Linting complete"

# Clean up
clean:
	rm -rf .venv/
	rm -rf $(E2E_VENV)/ .e2e-runtime/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "✅ Cleaned up"

# Run all CI quality checks
check: install-dev
	./.venv/bin/ruff check custom_components/smart_irrigation/
	./.venv/bin/black --check .
	@echo "✅ All CI checks passed"
