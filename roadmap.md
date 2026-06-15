# GoZappify — Sequenced Roadmap (from 2026-06-13)

Goal: get to "the lads installing the timesheet PWA from a link" as fast as is sensible,
WITHOUT leaving known security holes open in the live, paying product. Evenings-and-
weekends pace assumed. Each phase is tested on staging before production.

Guiding principle: protect what's already live (customers, revenue) before building new
things on top of it. The PWA is the rewarding build with the clear saving — it comes
right after the foundation is safe.

---

## WEEK 1 — Foundation + worst holes

### Session 1: Build the staging environment
- Follow STAGING_SETUP.md (Railway dashboard: duplicate prod → point at `staging`
  branch → separate database → sandbox PayPal creds → daily backups).
- Verify: push a trivial change to `staging`, see it deploy to the staging URL, prod
  untouched.
- Why first: every fix after this is tested safely before it touches real customers.
- Mostly dashboard clicking; Claude Code only for the CLAUDE.md update at the end.

### Session 2: PayPal webhook signature verification (AUDIT risk #2)
- The only internet-facing exploit. Forged events can grant free plans / lock out
  payers. `PAYPAL_WEBHOOK_ID` already exists in prod; staging uses the sandbox one.
- Test on staging with PayPal sandbox events, then ship to prod.

### Session 2 (same evening if time): IDOR fix (AUDIT risk #6)
- One-line `user_id` filter in employees.py labour logging + an isolation test.
- Tiny. Bundle it with the webhook session.

End of week 1: staging exists, the two worst security holes closed. Live product is
materially safer.

---

## WEEK 2 — Finish hardening

### Session 3: Encryption fail-hard checks (AUDIT risk #3)
- Make missing encryption keys crash at startup instead of silently degrading
  (prevents the "credentials bricked after a restart" trap).
- Encrypt Xero tokens at rest like QuickBooks already does.
- Verify on staging (with staging's own keys), then prod.

### Session 4: Money migration prep (AUDIT risk #4 — the big one)
- This is the careful one: Float → Numeric on the customer-facing money columns +
  a shared Decimal money() helper + tests. Touches real money data.
- REHEARSE on the staging database first (with a backup taken). Only promote to prod
  once staging proves the migration runs clean and totals are unchanged.
- May span two sessions. Don't rush it. This is exactly why staging was built first.

End of week 2: Sprint A essentially done. The live product is secure and its money
maths are sound. Now safe to build new features on top.

---

## WEEK 3+ — The timesheet PWA (the saving + the fun build)

Build per TIMESHEET_SPEC.md, in its phases, each tested on staging:

### Phase 1: Data model + migrations
- Extend Employee/LabourEntry (entry type, status, leave allowance, invoice link).
- Numeric for hours, never Float (lesson from risk #4).

### Phase 2: Employee entry form + validation
- Customer dropdown (from QB-synced customers), date, start/end, notes-required,
  red "you missed X" errors, same-date overlap flag.

### Phase 3: Leave balances
- Allowance in hours, decrements on Annual Leave entries, remaining shown to employee.

### Phase 4: Admin search/report/export + approve flow
- Date-range + customer search (the invoicing workflow), CSV export, approve-to-lock.

### Phase 5: Customer sync button
- Admin "Sync customers from QuickBooks" — fast, new customers appear in dropdowns.

### Phase 6: PWA shell + passkey login + offline queue
- Installable (manifest + service worker), biometric/passkey login (no email needed),
  offline entry that syncs when back online.
- THIS is the phase where it becomes installable from a link.

### Phase 7: Invoiced-status integration
- Mark entries invoiced when their hours go on an invoice — kills double-billing.

---

## How the lads get it on their phones (no App Store)

A PWA installs straight from a web link — no Apple/Google store, no fees, no review:
- **iPhone:** open the timesheet URL in Safari → Share button → "Add to Home Screen".
- **Android:** open the URL in Chrome → "Install app" banner → tap.
- Result: a home-screen icon that opens full-screen like a normal app, with their login.
- You ship updates by updating the website — instant, no store approval.

So onboarding is literally: text Artur, Byron and Simon a link + "add to home screen",
and they're clocking in. (Jack's gone — his seat is being cancelled this week.)

---

## The payoff at the end

Once the PWA replaces TSheets:
- Cancel TSheets (export history to CSV → Shared Drive archive first).
- Drop the 3 surplus Workspace seats (Artur/Byron/Simon — they only ever existed for
  TSheets logins; they don't use Workspace email and don't need Drive access).
- Your lads are user-zero on your own product, hardening it for real customers.
- "Built by an electrical contractor who runs his own firm on it" — your best
  marketing line, now literally true including timesheets.

---

## This week's concrete to-dos (parallel to the build, no coding)

- [ ] Cancel Jack's Workspace seat (migrate/forward his mail first, then delete in
      Admin console). Immediate saving + closes an ex-employee security loose end.
- [ ] Export TSheets history to CSV now and archive it (legal record-keeping; protects
      the data regardless of when you actually cancel TSheets).
- [ ] Dropbox → Drive migration, then cancel Dropbox (per stop-paying-twice.md).
- [ ] Move key spreadsheets to Sheets, then cancel Microsoft 365.
- [ ] Install on M5: VS Code, Google Drive, Rectangle, Parallels (for Lutron Designer),
      a password manager.
- [ ] Turn on 2-step verification for remaining Workspace users.

---

## Realistic timeline

- Week 1: staging + 2 worst security fixes
- Week 2: encryption + money migration (Sprint A done)
- Weeks 3–5: PWA built phase by phase
- ~End of next month: lads installing the PWA from a link; TSheets + 3 seats cancelled

Aggressive-but-honest version if you want the PWA sooner: do Week 1 (staging + PayPal
webhook + IDOR) then jump to the PWA, and slot the encryption + money-migration work in
between PWA phases. Defensible — the two worst holes are closed first — but the money
migration shouldn't slip too far, since every new feature adds money maths on top of the
Float problem.
