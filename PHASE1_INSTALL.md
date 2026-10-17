# Phase 1 reference — superseded by Phase 2

This file is retained as a historical summary of the initial Phase 1 implementation. **Use `PHASE2_INSTALL.md` for current backup, installation, migration, and test instructions.**

Phase 1 introduced the organized `source-files/` package, the `private-configs/tokens.env` convention, one SQLite database per Discord guild at `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`, `/setup public_tickets` database initialization, and numbered ticket channel names that reset after all tickets in a guild are closed.

Phase 2 builds on that code by strengthening atomic credit transactions, adding transaction audit fields and idempotency safeguards, and expanding the automated tests. Existing per-guild databases are migrated in place; create a Phase 1 backup before installing Phase 2. The old root-level Phase 0 database is not automatically imported.
