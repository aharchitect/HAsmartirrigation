# Contributing to Smart Irrigation

## Development Setup

### Prerequisites
- Python 3.13.2 or higher
- Git
- Docker Engine for the Home Assistant runtime suite
- on Windows:
   - Microsoft Visual C++ 14.0 or greater # Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd HAsmartirrigation
   ```

2. **Set up development environment**
   ```bash
   make setup
   ```
   This will create a Python 3.13 virtual environment and install all dependencies.

3. **Activate the environment**
   ```bash
   source .venv/bin/activate
   ```

4. **Set up environment variables** (for testing)
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

### Running Tests

```bash
make test
```

The Docker-backed suite boots a real Home Assistant Container on a random
loopback port. It is isolated from the normal test environment and does not use
personal Home Assistant configuration, credentials, weather providers, or
devices. Its Home Assistant image tag is derived from `requirements.test.txt`.

```bash
make test-e2e
```

The first run downloads the pinned image and creates `.venv-e2e`. To retain
sanitized configuration and container logs under `.e2e-artifacts/`, run:

```bash
make test-e2e-debug
```

Debug artifacts exclude authentication storage, tokens, databases, and secret
files. Both E2E targets install frontend dependencies and rebuild the panel
before pytest starts.

### Code Quality

**All CI checks:**
```bash
make check    # Run all CI quality checks
```

**Individual commands:**
```bash
make format   # Format code (black)
make lint     # Lint code (ruff)
```

### Available Make Commands

Run `make help` to see all available commands:
```bash
make help
```

### Pre-commit Hooks

Install pre-commit hooks to automatically run checks:

```bash
pre-commit install
```

### Deactivating Environment

When you're done developing:

```bash
deactivate
```

## Project Structure

- `custom_components/smart_irrigation/` - Main component code
- `tests/` - Unit tests
- `tests_e2e/` - Docker-backed Home Assistant runtime tests
- `test_*.py` - Integration test scripts
- `requirements-dev.txt` - Development dependencies
- `requirements.test.txt` - Testing dependencies
- `requirements.e2e.txt` - Isolated runtime-test dependencies
