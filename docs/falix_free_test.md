# Falix free-plan test deployment

This guide is for a **development test**, not a claim that the free plan has production-grade uptime.

## What Falix currently documents

Falix's public bot-hosting page documents the free plan as 512 MB RAM, 25% CPU, 2 GB storage, and a manual renewal about once per week. It lists crash reports/alerts on all plans, while automatic crash detection and restart are described as Premium features. It supports Python 3.7–3.13, so use Python 3.13 for this project's `requires-python = ">=3.13"`. See the live [Falix Discord bot hosting page](https://falixnodes.net/discord-bot-hosting) for current plan details.

Falix documents sub-users with configurable permissions. A Support preset can start/stop and view logs without allowing broad file/admin management. To let only a trusted friend start/restart the test bot, add a sub-user and grant the smallest possible server-control permissions; do not share your account password. Alternatively, Falix's External Start feature allows non-owner users with the server subdomain to request a start, but it's not an identity-restricted allowlist and is therefore less controlled.

## Deploy the 0.7.0 test build

1. Create a new Discord bot server in Falix and select the Python runtime, **Python 3.13**.
2. Upload the contents of this project ZIP. You should see `app.py`, `RunBot.py`, `requirements.txt`, `source-files/`, `private-configs/credentials.env.example`, and `docs/` in the server root.
3. Use the panel's Python/requirements installation action or its documented dependency installer to install `requirements.txt`. The dependencies include `discord.py`, `python-dotenv`, `psycopg[binary]`, and `pyzipper`.
4. Set `DISCORD_TOKEN` in Falix's secret/environment variables. Optionally set `GUILD_ID` to your test Discord server ID for test-server slash-command sync. Set `DATABASE_BACKEND=sqlite` for this first test. Leave `DATABASE_URL` blank. Do not upload real tokens to GitHub.
5. Configure the main file to `app.py` if Falix offers a main-file selector. Otherwise use the Python template's normal `python app.py` startup. If the free panel does not allow changing the main file or startup configuration, ask Falix support before trying to bypass that restriction.
6. Start the bot and inspect the live console. Wait for `Logged in as ...` and then test only in a development Discord server: `/setup admin_dashboard`, `/setup public_tickets`, event add/remove, invite-event start/end, audit-channel transcript output, scam reports, and ticket-number cycle behavior.
7. In the Admin Dashboard, set an Audit Log Channel with `Send Messages`, `Embed Links`, `Attach Files`, and `Read Message History`. Enable the bot's invite features only after granting `Manage Server` and testing attribution.
8. Configure Falix profile/server crash notifications. If the panel supports Discord webhook alerts on your plan, point them to a private operations channel. The application's own start/shutdown notice is separate: a forced kill cannot run the shutdown handler.
9. Add a trusted Falix sub-user with minimum server-control permissions if somebody else should start or stop the test deployment.

## Known free-plan compromises

- **Weekly renewal is still required.** Falix's free bot plan is not a zero-maintenance/no-expiry service.
- **Automatic restart after a crash is Premium.** The free plan offers crash reports/alerts, but don't assume a crashed process will come back by itself.
- The advertised free allocation is 512 MB RAM, 25% CPU, and 2 GB storage. This is much less than the X Systems special free-bot offer. If the bot exceeds memory or dependency-install space, review console logs before changing code.
- A hosting-panel backup is not the same as the encrypted per-server ZIP DM feature in this project. Configure `BACKUP_DISCORD_USER_ID` and `BACKUP_ENCRYPTION_PASSWORD` in the panel to enable the app-level backups. Each server is exported separately. Check the console for the number of successful DM deliveries; a failed/oversized DM is logged.
- This first test uses local SQLite, which lives on the host's file storage. It does **not** test remote PostgreSQL. After the app workflows are accepted, set up a valid PostgreSQL provider and perform a clean migration, then rerun the tests before using PostgreSQL.
- Free-plan renewal and shared-management terms can change. Re-check Falix's live documentation before relying on them.

## Official Falix guides

- [Discord bot hosting and plan details](https://falixnodes.net/discord-bot-hosting)
- [Manage sub-users and permissions](https://kb.falixnodes.net/falix/dashboard/automation/sub-users)
- [External server start](https://kb.falixnodes.net/falix/dashboard/automation/external-start)
- [Startup configuration](https://kb.falixnodes.net/falix/dashboard/setup/startup-configuration)
- [Crash notification settings](https://kb.falixnodes.net/falix/account/profile/profile-settings)
