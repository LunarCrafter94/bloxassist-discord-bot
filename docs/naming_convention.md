# Project naming conventions

- Project/repository directory: `bloxfruits-helper-credit-bot` (kebab-case).
- Source root: `source-files/`.
- Importable Python package: `bloxfruits_helper_credit_bot/` (snake_case).
- Variables and parameters: `camelCase`.
- Application functions and methods: `PascalCase`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Python modules/packages: `snake_case`.
- SQL tables and columns: `snake_case`.
- Assets: descriptive filenames, such as `bot-client_icon.png` and `bot-client_banner.png`.
- Main launcher: `RunBot.py`.

Required Python, unittest, and Discord framework hooks retain their required spellings, including `__init__`, `callback`, `setup_hook`, `close`, Discord event names, and unittest lifecycle methods.

This is the project's established house style. It intentionally differs from the Python community's usual preference for `snake_case` function and variable names, so follow the project convention for consistency when contributing.
