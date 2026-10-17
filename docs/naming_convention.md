# Project naming convention

- Project root/repository: `bloxfruits-helper-credit-bot` (kebab-case).
- Source code root: `source-files/`.
- Importable Python package: `bloxfruits_helper_credit_bot/` (snake_case).
- Variables/parameters: `camelCase`.
- Application functions/methods: `PascalCase`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Modules/packages: `snake_case`.
- Images and other visual assets: descriptive filenames, such as `bot-client_icon.png` and `bot-client_banner.png`.
- Master launcher: `RunBot.py`.
- Required Python and discord.py hooks (`__init__`, `callback`, `setup_hook`, `close`, Discord event names, and unittest lifecycle names) retain framework spelling.
- SQL table and column names use `snake_case`.

This house style intentionally differs from PEP 8's usual `snake_case` recommendation for Python functions/variables; the project prioritizes the owner's established visual consistency.
