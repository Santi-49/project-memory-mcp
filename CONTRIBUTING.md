# Contributing to Project Memory MCP

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Be respectful, inclusive, and professional. We welcome contributions from people of all backgrounds and experience levels.

## Getting started

### Prerequisites

- Python 3.13+
- Git

### Setup development environment

```bash
# Clone the repository
git clone https://github.com/YOUR-ORG/project-memory-mcp.git
cd project-memory-mcp

# Create a virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-cov
```

### Run tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html

# Run specific test
python -m pytest tests/tests.py::TestGuideResource -v
```

## Making contributions

### For documentation changes

1. Edit the relevant file in `skill/references/` or `docs/`
2. Test by running `python src/server.py` and inspecting the resource
3. Commit with a clear message, e.g., "docs: update quick-reference for new rule"

### For code changes

1. **Create a feature branch**: `git checkout -b feature/your-feature-name`
2. **Write your code**: Follow the existing code style
3. **Add tests**: Ensure your changes are covered by tests
4. **Update documentation**: If you change behavior, update the relevant skill guide
5. **Run tests**: `python -m pytest tests/ -v` must pass
6. **Commit with clear messages**:
   ```
   feat: add new tool for X
   
   - Details of what was added
   - Why it was needed
   - How to use it
   ```

### Code style

- Follow PEP 8
- Use type hints (Python 3.13+)
- Keep functions focused and well-documented
- Add docstrings to public functions

Example:

```python
def normalize_newlines(content: str) -> str:
    """Normalize escape sequence newlines to actual newlines.
    
    Converts literal \\n, \\r\\n, \\r to actual newline characters.
    This prevents content from being written with escaped sequences.
    
    Args:
        content: The string to normalize
        
    Returns:
        The normalized string with actual newlines
    """
    content = content.replace("\\r\\n", "\n")
    content = content.replace("\\n", "\n")
    content = content.replace("\\r", "\n")
    return content
```

## Submitting changes

1. **Push your branch**: `git push origin feature/your-feature-name`
2. **Create a Pull Request**:
   - Fill in the PR template
   - Describe why this change is needed
   - Reference any related issues
   - Include before/after examples if applicable
3. **Address feedback**: Respond to review comments and make requested changes
4. **Merge**: Once approved, your PR will be merged

## Reporting bugs

Use GitHub Issues to report bugs. Include:

- **Description**: Clear explanation of the bug
- **Steps to reproduce**: Exact steps to trigger the bug
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happens
- **Environment**: Python version, OS, any relevant config
- **Error messages**: Full stack traces or error output

## Requesting features

Use GitHub Issues or Discussions to suggest features. Describe:

- **Use case**: Why is this feature needed?
- **Proposed solution**: How should it work?
- **Alternatives**: Any alternative approaches you've considered

## Documentation

When you add or change features, please update:

- **Docstrings** in the code
- **Relevant skill guides** in `skill/references/`
- **README.md** if it affects usage
- **Tests** to document expected behavior

The skill guides (`quick-reference.md`, `guide.md`, etc.) are the primary user-facing documentation and are served as MCP resources. Keep them:

- Clear and concise
- Up-to-date with code changes
- Organized with headers and tables
- Linked to related resources

## Testing guidelines

Tests should:

- Cover both happy paths and error cases
- Be isolated and not depend on execution order
- Use descriptive names: `test_normalize_newlines_converts_escaped_to_actual()`
- Include docstrings explaining what's being tested

Example:

```python
def test_normalize_newlines_converts_escaped_to_actual():
    """normalize_newlines should convert \\n to actual newlines."""
    content = "Line 1\\nLine 2\\r\\nLine 3"
    expected = "Line 1\nLine 2\nLine 3"
    assert normalize_newlines(content) == expected
```

## Questions?

- Check the [README](README.md) and skill guides
- Open a GitHub Discussion for questions
- Open an Issue if you think you've found a bug

---

**Thank you for contributing!** 🎉
