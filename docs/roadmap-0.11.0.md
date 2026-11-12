# BloxAssist v0.11.0 — Administration and Configuration Improvements

**Status:** Planning / Proposed
**Base release:** v0.10.0
**Target branch:** `development/v0.11.0`

---

## 1. System Access Control — Configurable Role-Based Permissions

**Objective:** Introduce a centralized, server-specific permission-management system that allows the server owner to control which Discord roles can access individual BloxAssist administrative systems and restricted commands.

### Proposed features

- Add a **System Access Control** section to the Admin Dashboard.
- Allow the server owner to designate the roles authorized to manage system permissions (**System Access Managers**).
- Allow the server owner and authorized System Access Managers to assign or remove role-based access to individual BloxAssist systems.
- Keep permission assignments independent for each system.
- Provide an **Effective Access Preview** so an authorized administrator can inspect which systems a selected role or member can access.

### Systems covered

The initial permission inventory should cover:

- `/diagnostics`
- Server Statistics
- `/member-activity`
- Other-member `/credit-history`
- Other-member `/ticket-history`
- `/reports` and report moderation (including `/report-review`)
- Admin Dashboard configuration
- Credit management and adjustments, including `/add`, `/deduct`, and `/penalty`

The owner may decide which roles, if any, receive access to each system. Granting access to one system must not automatically grant access to another.

### Security requirements

1. The actual Discord server owner must always retain unrestricted administrative access.
2. Each covered system must have independently configurable permissions.
3. Granting access to one system must not automatically grant access to other restricted systems.
4. Only the server owner or authorized System Access Managers may modify system access configurations.
5. The server owner controls the System Access Manager designation. Delegated managers must not be able to promote themselves, grant themselves additional privileges, or modify their own manager designation.
6. Every permission change must be recorded in the configured Audit Log Channel, identifying the actor and the affected role or permission.
7. Authorization must be enforced by BloxAssist during slash commands and relevant component interactions; Discord channel permissions alone are not sufficient.
8. Recheck authorization when users interact with buttons, selects, modals, and pagination controls. A previously opened interaction must not preserve access after permission is revoked.
9. Store permissions separately for each Discord server and persist them across restarts.
10. Preserve existing security restrictions by default. In particular, `/diagnostics` and credit adjustments remain owner-only unless the server owner explicitly changes the applicable policy. Delegated managers cannot change those protected-command defaults or grant themselves access to them.

### Acceptance tests

- Unauthorized roles cannot access restricted systems.
- Assigned roles can access only the systems granted to them.
- Granting one system does not grant access to another system.
- Revoking a role immediately removes its access, including from existing component interactions.
- Ordinary members cannot modify system permissions.
- Only the owner can designate or change System Access Managers.
- Access managers cannot promote themselves or alter their own manager designation.
- The owner cannot lose access.
- Permission changes are audited and survive bot restarts.
- One server's permission configuration cannot affect another server.

---

## 2. Boolean Input Improvements — Dropdown Selection

**Objective:** Improve the Admin Dashboard configuration experience by replacing free-text inputs for Boolean-only settings with predefined Discord dropdown/select choices.

### Proposed changes

Review all Admin Dashboard configuration inputs that accept only Boolean values. At minimum, cover these settings:

| Current setting | Proposed dropdown options |
|---|---|
| Enable invite rewards? | Enabled / Disabled |
| Repeat inviter penalty after rejoin? | Every rejoin/leave cycle / Once per invited member |

The repeat-inviter setting is a **policy choice**, not a generic enabled/disabled switch. Its labels must explain the actual behavior.

### Implementation requirements

1. Identify all Dashboard configuration fields that accept only Boolean values.
2. Replace the relevant free-text Boolean inputs with predefined Discord select components.
3. Display human-readable labels rather than requiring users to type `true`, `false`, `yes`, or `no`.
4. Preserve the current database representation:
   - `true` = Enabled / the selected repeat-per-rejoin policy, as applicable.
   - `false` = Disabled / once per invited member, as applicable.
5. Preserve existing default values and behavior. In particular, repeat-per-rejoin inviter penalties remain disabled by default (`false`), corresponding to **Once per invited member**.
6. Validate the selected value before saving. Missing or invalid selections must not silently change a setting.
7. Display the currently configured selection when the configuration is reopened.
8. Provide a clear confirmation after saving.
9. Ensure select interactions are compatible with the installed `discord.py` version and the project's current component patterns.

### Acceptance tests

- Users can select either option without typing Boolean values.
- Each selection is saved to the existing setting correctly.
- Reopening the configuration displays the saved selection.
- Existing database values remain compatible; no unnecessary schema migration is introduced.
- Invalid or missing selections cannot accidentally change settings.
- Existing invite reward and inviter leave-penalty behavior remains unchanged.
- Existing defaults are retained, including repeat-per-rejoin being disabled by default.

---

## 3. Quality Assurance and Regression Testing

### System Access Control

- Owner access cannot be removed.
- Unauthorized users cannot access restricted commands or components.
- Previously opened dashboard interactions cannot bypass newly changed permissions.
- Permission changes take effect immediately.
- Access-manager designation is owner-controlled and cannot be self-modified by a delegated manager.
- Server configurations remain isolated.
- Existing moderator and ticket-staff configurations remain compatible.
- Owner-only diagnostics and credit-adjustment restrictions remain intact unless explicitly changed by the owner.

### Boolean configuration

- Dropdown choices correctly save and reload the corresponding setting values.
- Existing database representations and defaults are preserved.
- Invalid or missing choices are rejected safely.
- SQLite and PostgreSQL behavior remains consistent.
- Existing invite rewards and inviter leave-penalty behavior is not unintentionally changed.

### Release validation

Run the established project verification commands:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests tools

.\.venv\Scripts\python.exe -m unittest discover -s tests
```

- Add regression tests for new permission checks and dropdown interactions.
- Complete live acceptance testing in a separate Discord test server before deploying to the real server.
- Do not modify production database records merely to test the new interfaces.

---

## 4. Non-Goals

The following are not part of the initial v0.11.0 scope:

- Complete per-server backup architecture redesign.
- New backup encryption infrastructure.
- Backup Health Dashboard.
- Unrelated ticket workflow or credit-management redesigns.

These may be evaluated for later releases.

---

## 5. Release Objective

Make BloxAssist safer and easier to administer by introducing granular, server-specific staff access controls and clearer configuration interfaces, while preserving the existing behavior and security guarantees established in v0.10.0.

**Implementation status:** These features are proposed only. They are not implemented or verified in the current build.
