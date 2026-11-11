# BloxAssist v0.11.0 — Administration and Configuration Improvements

**Status:** Planning
**Base release:** v0.10.0
**Target branch:** `development/v0.11.0`

## 1. Configurable System Access Control (RBAC)

Introduce configurable, server-specific staff permissions that allow the server owner to control access to individual BloxAssist systems.

### Proposed capabilities
- Configure staff-role access independently for each system.
- Support different permission assignments for Credit Management, Ticket Management, Reports and Moderation, Invite Rewards, and Admin Dashboard.
- Enforce permissions for both slash commands and interactive components.
- Revalidate permissions during button, select-menu, modal, and pagination interactions.
- Record permission changes in the audit log, including the actor and affected role or member.
- Prevent managers from modifying their own roles or granting themselves additional permissions.
- Guarantee that the actual Discord server owner retains full access.
- Persist permission configurations independently for each Discord server.

### Additional interface improvement
**Effective Access Preview:** Allow authorized administrators to inspect the effective system permissions of a selected role or member.

## 2. Boolean Input and Configuration Improvements

Standardize binary configuration controls in the Admin Dashboard.

### Initial settings to cover
- Invite Rewards: Enabled / Disabled.
- Repeat Inviter Leave Penalty: Enabled / Disabled.

### Compatibility requirements
- Preserve existing database representations.
- Preserve established default values.
- Preserve validation behavior.
- Keep repeat-per-rejoin inviter penalties disabled by default.
- Avoid unnecessary database migrations where existing settings can be reused.

## 3. Quality Assurance and Regression Testing

### RBAC
- Owner access cannot be removed.
- Unauthorized users cannot access restricted commands or components.
- Previously opened dashboard interactions cannot bypass newly changed permissions.
- Permission changes take effect immediately.
- Server configurations remain isolated.
- Existing moderator and ticket-staff configurations remain compatible.

### Configuration
- Binary controls correctly save and reload settings.
- Existing defaults are preserved.
- Invalid values are rejected safely.
- SQLite and PostgreSQL behavior remains consistent.

### Release validation
- Python compilation succeeds.
- Existing automated tests pass.
- New regression tests cover the added functionality.
- Live acceptance testing is completed in a separate Discord test server before deployment.

## 4. Non-Goals

The following are not part of the initial v0.11.0 scope:
- Complete per-server backup architecture redesign.
- New backup encryption infrastructure.
- Backup Health Dashboard.
- Unrelated ticket workflow or credit-management redesigns.

These may be evaluated for later releases.

## 5. Release Objective

Make BloxAssist easier and safer to administer by introducing granular staff access controls and consistent configuration interfaces, while preserving the stability and existing behavior established in v0.10.0.
