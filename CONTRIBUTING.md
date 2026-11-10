# Contributing to HIL Debug Workbench

Thanks for your interest in contributing! This document provides guidelines for contributing to the project.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/apandya55/hil_debug_workbench.git
   cd hil_debug_workbench
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install in development mode**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=hil_cli --cov=dashboard --cov=tui --cov-report=html

# Run specific test file
pytest tests/test_detector.py

# Run with verbose output
pytest -v
```

## Code Quality

We use several tools to maintain code quality:

- **ruff** — fast Python linter and formatter
- **mypy** — static type checker
- **pre-commit** — automated checks before commits

Run quality checks:

```bash
# Format code
ruff format .

# Lint code
ruff check . --fix

# Type check
mypy hil_cli dashboard tui
```

## Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write clear, documented code
   - Add tests for new functionality
   - Update documentation as needed
   - Follow existing code style

3. **Run tests and quality checks**
   ```bash
   pytest
   ruff check .
   mypy hil_cli
   ```

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```
   
   Follow [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation changes
   - `test:` adding tests
   - `refactor:` code refactoring
   - `chore:` maintenance tasks

5. **Push and create a pull request**
   ```bash
   git push origin feature/your-feature-name
   ```

## Adding New Board Support

To add support for a new chip family:

1. Add VID/PID mappings to `hil_cli/detector.py`
2. Add crash patterns to `hil_cli/serial_monitor.py`
3. Add toolchain prefix logic to `hil_cli/config.py`
4. Update documentation

## Testing Hardware Changes

When testing hardware-related changes:

1. Use the mock fixtures in `tests/conftest.py`
2. Document which physical boards you tested with
3. Include serial output samples in PR description
4. Test both ESP32 and RP2040 families if possible

## Documentation

- Update README.md for user-facing changes
- Add docstrings to new functions/classes
- Update hil.yaml.example for new config options
- Add examples to `docs/examples/` for complex features

## Questions?

Open an issue or reach out to the maintainers.
