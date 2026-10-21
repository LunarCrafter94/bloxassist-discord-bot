# Historical documentation and scripts

Historical documents are retained for context, not as current operating instructions.

- `releases/historical-installation-and-changelogs.zip` contains the previous root `INSTALL.md` and `CHANGELOG.md` plus phase-specific installation/changelog notes and release documents. They may reference older paths, commands, and permission behavior.
- `original-reference-docs/` contains snapshots of the earlier architecture, naming, owner-requirements, and transaction-safety documents.
- `pre-cleanup-2026-10-18_030443/` contains a pre-cleanup README snapshot retained for historical reference.
- `../installation_and_operations.md`, `../backup_and_restore.md`, and `../architecture.md` are the maintained current documents. The root `README.md` links to these docs and to `docs/release_history.md`.
- `tools/history/legacy-release-scripts/` holds old phase-specific maintenance scripts; do not use them for routine backups. Use `tools/Backup-Project.ps1` and `tools/Test-Project.ps1` instead.
