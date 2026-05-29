# Contributing to GitMoji AI

First off, thank you for considering contributing to GitMoji AI! 🎉

## 🚀 Quick Contribution Guide

### Bug Reports

1. Check if the bug is already reported in [Issues](https://github.com/sochiautoparts/gitmoji-ai/issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (Python version, OS, etc.)

### Feature Requests

1. Check existing [Issues](https://github.com/sochiautoparts/gitmoji-ai/issues) first
2. Create a new issue with the `enhancement` label
3. Describe the feature and why it would be useful

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/amazing-feature`
3. Make your changes
4. Add tests for new functionality
5. Run tests: `pytest`
6. Run linter: `ruff check src/`
7. Commit with GitMoji AI: `gmai commit` 😉
8. Push: `git push origin feat/amazing-feature`
9. Open a Pull Request

### Development Setup

```bash
# Clone
git clone https://github.com/sochiautoparts/gitmoji-ai.git
cd gitmoji-ai

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest -v

# Run linter
ruff check src/ tests/
```

### Code Style

- Follow PEP 8
- Use type hints
- Write docstrings for public functions
- Keep functions focused and small
- Max line length: 100 characters

### Commit Messages

We follow Conventional Commits:

```
feat: add new feature
fix: resolve bug
docs: update documentation
style: formatting changes
refactor: code refactoring
test: add tests
chore: maintenance tasks
```

Or just use GitMoji AI: `gmai commit` 😄

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.
