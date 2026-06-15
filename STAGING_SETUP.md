# STAGING_SETUP.md — Build a real Railway staging environment

Goal: a second Railway environment that auto-deploys from the `staging` branch, with
its OWN separate database, so changes can be tested on a live URL before they ever
reach production. This is the safe ground the Sprint A fixes need — especially the
Float→Decimal money migration, which must be rehearsed on a non-production database.

IMPORTANT: most of this is done in the Railway dashboard (clicking), NOT in Claude Code.
Claude Code can't click in Railway. Do the dashboard steps yourself; Claude Code helps
only with the repo-side verification noted at the end.

Current state (2026-06-13): ONE environment only — `production`, deploys from `master`.
The `staging` git branch exists but deploys nowhere.

---

## Part A — Create the staging environment (Railway dashboard)

1. Open the project in Railway. Click the **environment dropdown** (top bar, says
   "production") → **+ New Environment** → **Duplicate Environment** → duplicate
   `production`.
   - Duplicating copies the services, variables, and config, so the staging app is
     configured like production from the start. Railway will stage the changes for
     review before deploying — that's expected.
   - Name it `staging`.

2. You now have a `staging` environment with its own app service AND its own Postgres
   (the duplicate creates a separate database — confirm this; the staging app must NOT
   point at the production database).

## Part B — Point staging at the staging branch

3. In the `staging` environment → app service → **Settings → Source** → set the
   **trigger branch** to `staging` (production stays on `master`).
   - From now on: push to `staging` → staging env deploys; push to `master` →
     production deploys. The workflow in CLAUDE.md finally becomes real.

## Part C — Environment variables (the careful bit)

4. In the `staging` environment → app service → **Variables**. The duplicate copies
   production's values, which is mostly fine, BUT review these specifically:
   - **DATABASE_URL** — must point at the STAGING Postgres, not production. (Railway
     usually wires this automatically when both are in the same environment. Verify it.)
   - **Encryption keys** (`TOKEN_ENCRYPTION_KEY`, `EMAIL_TOKEN_ENCRYPTION_KEY`,
     `SECRET_KEY`) — fine to differ from production; if duplicated they'll work, but
     ideally generate fresh ones for staging so a leak of one env never exposes the other.
   - **PayPal** — point staging at **PayPal SANDBOX** credentials + sandbox
     `PAYPAL_WEBHOOK_ID`, never the live PayPal account. You do not want test
     subscriptions hitting real money.
   - **QuickBooks / Xero / Gmail OAuth** — these use redirect URLs tied to a domain.
     The staging app has a different URL, so either use sandbox/dev OAuth apps for
     staging or accept that live-integration testing happens on production. For now,
     getting the core app + database on staging is the win; OAuth-on-staging can be a
     follow-up.
   - **CRON_SECRET** — fine to differ; just ensure it's set (not empty) so staging's
     cron endpoints aren't fail-open.

5. Region: set the staging app + database to the same region as production
   (Amsterdam / europe-west4) for consistency.

## Part D — Backups

6. In the `staging` Postgres → **Backups** → schedule daily (less critical than
   production, but cheap and tidy).

## Part E — Verify staging works

7. Make a trivial visible change on the `staging` branch (e.g. a tiny landing-page
   text tweak), push to `staging`, and confirm:
   - the STAGING environment deploys (not production),
   - the staging URL shows the change,
   - production is unchanged.
   Then revert the tweak. This proves the pipeline end to end.

## Part F — Repo-side (Claude Code CAN help here)

8. Ask Claude Code to confirm the branch/deploy wiring assumptions in CLAUDE.md are now
   correct and update the "no staging environment exists" notes (Stack, deploy rule #3,
   Deployment section, Known context) to reflect that staging is now live. Commit to
   staging, verify on the staging deploy, then merge to master.

---

## Once staging is real, the Sprint A queue (all tested on staging first):

1. **PayPal webhook signature verification** (AUDIT risk #2 — internet-facing). Uses the
   `PAYPAL_WEBHOOK_ID` that already exists in prod; staging uses the sandbox one.
2. **IDOR fix** in employees.py labour logging (AUDIT risk #6 — one-line `user_id` filter
   + isolation test).
3. **Encryption fail-hard checks** (AUDIT risk #3 — make missing keys crash at startup
   instead of silently degrading; encrypt Xero tokens like QB).
4. **Float → Decimal money migration** (AUDIT risk #4 — the big one; rehearse on the
   staging database first, with a backup taken, before production).

## Reminder

This whole task is mostly Railway dashboard clicking. Claude Code's role is small
(Part F). Don't ask Claude Code to "build the staging environment" — it can't reach
Railway. Follow Parts A–E yourself, then bring Claude Code in for Part F.
