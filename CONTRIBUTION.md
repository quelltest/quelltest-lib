 # Contributing to quelltest-lib

Thank you for your interest in contributing to quelltest-lib!

quelltest-lib helps developers discover untested edge cases before they reach production. Contributions that improve reliability, test coverage, documentation, and developer experience are welcome.

---

## Ways to Contribute

You can contribute by:

- Improving edge-case detection algorithms
- Enhancing Production Readiness Score logic
- Improving CLI commands and documentation
- Adding support for additional Python project structures
- Improving false-positive detection
- Writing or expanding automated tests
- Improving SDK examples
- Optimizing performance
---

## Development Setup

Step 1: Clone the repository.

Step 2: Create a virtual environment.

Step 3: Install development dependencies.

Step 4: Run the test suite before submitting changes.

Step 5: Verify that your changes do not introduce regressions.

---

## Development Guidelines

Please ensure that:

* Changes are focused on a single issue.
* Code follows the existing project structure and style.
* Documentation is updated when necessary.
* New functionality includes appropriate tests where applicable.
* Existing functionality is not broken.

---

## Pull Request Guidelines

Before opening a Pull Request:

* Review your changes carefully.
* Test your changes locally.
* Reference the related issue.
* Keep the PR focused and easy to review.

Example:

```text
Fixes #123
```

---

## Testing

Before opening a Pull Request, please ensure that you have run the project's development checks:

```bash
uv sync --dev
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format --check .
```

Please ensure that all tests pass successfully and no linting or formatting issues remain before submitting your changes.

---
## Before Opening a Pull Request

Please ensure that:

- Existing tests pass successfully.
- Ruff reports no issues.
- Code formatting is correct.
- Documentation is updated if required.
- Changes remain focused on a single issue.

---
## Reporting Issues

When reporting bugs:

* Provide clear reproduction steps.
* Include expected and actual behavior.
* Share relevant logs or screenshots when applicable.

---

## Community Standards

By participating in this project, you agree to follow the project's Code of Conduct.

Please review `CODE_OF_CONDUCT.md` before contributing.

---

Thank you for helping improve quelltest-lib!
