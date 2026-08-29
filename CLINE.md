# Agent Guidelines for Python & Full-Stack Development

This document defines the coding standards, architectural principles, and best practices that **Cline** must follow when generating code for both **Python backend** and **frontend (NiceGUI, Textual, Flet)**.  
Adherence to these guidelines ensures clean, maintainable, high-performance, and scalable applications across the entire stack.

---

## 1. Code Style & Documentation (Python)

### 1.1 Google-Style Docstrings
All public modules, classes, functions, and methods **must** include Google-style docstrings.

**Example:**
```python
def calculate_vram(params: float, layers: int) -> float:
    """Calculate the approximate VRAM required for a model.

    Args:
        params: Number of model parameters in billions.
        layers: Number of transformer layers.

    Returns:
        Estimated VRAM in gigabytes.

    Raises:
        ValueError: If params or layers are non-positive.
    """
    if params <= 0 or layers <= 0:
        raise ValueError("params and layers must be positive")
    return params * 1.2 * layers * 2 / 1024
```

### 1.2 Type Hints
- Use Python type hints for all function parameters and return values.
- Leverage `typing` module for complex types (e.g., `List`, `Dict`, `Optional`, `Union`).
- Prefer Python 3.10+ style hints when possible (e.g., `list[str]`, `dict[str, int]`).

### 1.3 Naming Conventions
- **Classes**: `PascalCase`
- **Functions/Methods**: `snake_case`
- **Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private/Protected**: prefix with `_`

### 1.4 Line Length & Formatting
- Maximum line length: **100 characters**.
- Use 4 spaces for indentation.
- Follow PEP 8 guidelines; use `black` or `ruff` for automatic formatting.

---

## 2. Logging System

### 2.1 Requirements
- All log messages **must** be in English.
- Logging must be configurable via environment variables or configuration files.
- Log files are stored in `./logs/` relative to the project root.
- Log files are rotated daily (by date) and automatically cleaned after a configurable retention period.

### 2.2 Implementation
Use Python's built-in `logging` module with a custom configuration.

**Example configuration:**
```python
import logging
import logging.handlers
from pathlib import Path

def setup_logging(level: str = "INFO", log_dir: Path = Path("./logs")):
    """Configure application logging with daily rotation.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory to store log files.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app_{datetime.now():%Y-%m-%d}.log"

    handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    console = logging.StreamHandler()
    console.setLevel(level)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.addHandler(handler)
    root.addHandler(console)
```

### 2.3 Usage
- Use `logging.getLogger(__name__)` to create module-specific loggers.
- Always include contextual information in log messages (e.g., user ID, request ID).
- Log exceptions with `logger.exception("msg")` to include stack trace.

---

## 3. Modular Design

### 3.1 Project Structure
Organize code into clear, cohesive modules that separate **core logic**, **backend services**, **frontend views**, and **modules**.

```
project/
├── src/
│   ├── core/                          # Shared core logic
│   │   ├── __init__.py
│   │   ├── config.py                  # Configuration management
│   │   ├── constants.py
│   │   ├── utils.py
│   │   └── logging_setup.py
│   ├── modules/                       # Independent business modules
│   │   ├── __init__.py
│   │   ├── module_a/                  # Each module is self-contained
│   │   │   ├── __init__.py
│   │   │   ├── service.py
│   │   │   ├── models.py
│   │   │   └── interfaces.py
│   │   └── module_b/
│   │       └── ...
│   ├── frontend/                      # All frontend implementations
│   │   ├── __init__.py
│   │   ├── core/                      # Shared frontend components
│   │   │   ├── __init__.py
│   │   │   ├── components.py
│   │   │   ├── i18n.py                # Language support
│   │   │   ├── theme.py               # Theme management
│   │   │   └── store.py               # User/application state
│   │   ├── nicegui/                   # NiceGUI >=3.16.0 implementation
│   │   │   ├── __init__.py
│   │   │   ├── app.py
│   │   │   ├── pages/
│   │   │   ├── components/
│   │   │   └── routes.py
│   │   ├── textual/                   # Textual >=8.2.8 TUI implementation
│   │   │   ├── __init__.py
│   │   │   ├── app.py
│   │   │   ├── screens/
│   │   │   └── widgets/
│   │   └── flet/                      # Flet 0.86.5 implementation
│   │       ├── __init__.py
│   │       ├── app.py
│   │       ├── views/
│   │       └── controls/
│   ├── backend/                       # (Optional) If API server separate
│   │   ├── __init__.py
│   │   └── api.py
│   └── app.py                         # Main entry point (launcher)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── frontend/                      # Frontend-specific tests
├── logs/
├── config/
│   ├── default.yaml
│   ├── development.yaml
│   └── production.yaml
├── scripts/                           # Build/deploy scripts
├── requirements/
│   ├── base.txt
│   ├── nicegui.txt
│   ├── textual.txt
│   └── flet.txt
├── pyproject.toml
└── README.md
```

### 3.2 SOLID Principles (Apply to both backend and frontend)
- **Single Responsibility**: Each class/module/component should have one reason to change.
- **Open/Closed**: Extend functionality via inheritance/plugins, not modification.
- **Liskov Substitution**: Subtypes must be substitutable for their base types.
- **Interface Segregation**: Use small, focused interfaces.
- **Dependency Inversion**: Depend on abstractions, not concretions.

### 3.3 Configuration Management
- Use `pydantic-settings` or `python-dotenv` for backend configuration.
- For frontend, store user preferences (language, theme) in a dedicated store (e.g., `frontend/core/store.py`) and persist via local storage or config files.
- Support environment variable overrides for both.

### 3.4 Frontend Framework Integration
- **Supported Frameworks**: NiceGUI (>=3.16.0), Textual (>=8.2.8), Flet (>=0.86.5).
- Each frontend is independent and launchable via a dedicated command (e.g., `python -m src.frontend.nicegui.app`, `textual run src.frontend.textual.app`).
- All frontend implementations must consume the same core business logic and data via the `core` and `modules` layers.
- Communication between frontend and backend modules:
  - Use **dependency injection** to pass service instances.
  - Avoid direct frontend-to-module coupling; always go through interfaces defined in `modules/interfaces.py`.
- Each frontend must be **componentized** with reusable widgets/views.
- Responsive design is mandatory for NiceGUI and Flet; Textual should follow adaptive layout patterns.

### 3.5 Frontend Feature Requirements
All frontend implementations must support:
- **Language switching** (i18n): Use a central translation store (e.g., `frontend/core/i18n.py`) that holds key-value pairs for at least English and Chinese.
- **Theme switching**: Light/dark mode toggle, with persistent user preference.
- **User switching**: Simulated multi-user support (store user context in `frontend/core/store.py`).
- **Configuration persistence**: Save user settings (language, theme) to local storage or a config file.
- A clean, modern, and intuitive UI consistent across frameworks as much as possible.

---

## 4. High-Performance Design

- Use `asyncio` for I/O-bound tasks (network, file I/O) in backend and frontend (if async frameworks).
- For CPU-bound tasks, use `multiprocessing` or `concurrent.futures`.
- Use `functools.lru_cache` or `cachetools` for expensive function results.
- For databases, use connection pooling and batch operations.
- Use context managers (`with`) for resource management.
- Add `@profile` decorators for performance-critical functions; log warnings when a function exceeds a defined threshold.

---

## 5. Extensibility & Future-Proofing

- Use design patterns: **Factory**, **Strategy**, **Observer**, **Dependency Injection**.
- Support plugin architecture via `importlib` (backend) and dynamic component registration (frontend).
- Version APIs (e.g., `/v1/`, `/v2/`) if exposing backend endpoints.
- Make behavior configurable via feature flags.

---

## 6. Testing & Documentation

- Write unit tests for all core logic (using `pytest` for backend, and appropriate test runners for frontend – e.g., `pytest-nicegui`, `pytest-textual`, or `flet.test`).
- Coverage ≥80%.
- Maintain a clear `README.md` with setup and run instructions for each frontend.
- Generate API docs using `pdoc` or `Sphinx`.

---

## 7. General Coding Practices

- **Error Handling**: Use custom exceptions (inherit from `Exception`) for domain errors.
- **Immutability**: Prefer immutable data structures (e.g., `dataclass(frozen=True)`, `NamedTuple`).
- **Type Safety**: Use `mypy` for static type checking (backend) and static analysis for frontend (if TypeScript optional).
- **Linting**: Use `ruff` or `pylint` for Python, and framework-specific linters for frontend.
- **Formatting**: Use `black` or `ruff format`.

---

## 8. Example: Implementing a Module and Frontend Integration

**Module Interface (`modules/module_a/interfaces.py`)**:
```python
from abc import ABC, abstractmethod

class DataService(ABC):
    @abstractmethod
    def get_data(self, query: str) -> dict:
        """Fetch data based on query."""
```

**Module Implementation (`modules/module_a/service.py`)**:
```python
import logging
from .interfaces import DataService

logger = logging.getLogger(__name__)

class MyDataService(DataService):
    def get_data(self, query: str) -> dict:
        logger.info("Processing query: %s", query)
        return {"result": "data", "query": query}
```

**Frontend Component (`frontend/core/components.py`)**:
```python
from nicegui import ui
from modules.module_a.interfaces import DataService

def create_data_view(service: DataService):
    """Reusable view component for displaying data."""
    with ui.card():
        ui.label("Data Viewer")
        ui.input("Query", on_change=lambda e: update(e.value))

        def update(query: str):
            data = service.get_data(query)
            ui.notify(f"Fetched: {data}")
```

**Frontend App (`frontend/nicegui/app.py`)**:
```python
from nicegui import ui
from modules.module_a.service import MyDataService
from frontend.core.components import create_data_view

service = MyDataService()

@ui.page('/')
def main():
    create_data_view(service)

ui.run()
```

---

## 9. Checklist for Code Generation

Before finalizing code, ensure:

### Backend
- [ ] All functions have Google-style docstrings.
- [ ] Type hints are present for parameters and returns.
- [ ] Logging is set up with daily rotation.
- [ ] Module structure follows the recommended project layout.
- [ ] SOLID principles are respected.
- [ ] Performance considerations (caching, pooling) are addressed.
- [ ] The code is extensible (interfaces, config-driven).
- [ ] Unit tests are included (or at least testable design).
- [ ] No hard-coded values; all configurable.
- [ ] All log messages are in English.
- [ ] Error handling is robust (custom exceptions, validation).

### Frontend
- [ ] All reusable components are modular and placed in `frontend/core/components.py`.
- [ ] Language, theme, and user settings are managed via a central store.
- [ ] The frontend supports at least language switching (i18n) and theme toggle.
- [ ] The implementation is responsive (NiceGUI/Flet) or adaptive (Textual).
- [ ] Frontend communicates with backend only through core/module interfaces (no direct coupling).
- [ ] Each frontend (NiceGUI, Textual, Flet) is independently launchable.
- [ ] Preferences (language, theme) are persisted across sessions.

---

**Cline must strictly adhere to these guidelines when generating code.**  
If any requirement is unclear, ask for clarification before proceeding.