# STOP PAYING TWICE — Software & Subscription Consolidation Plan

Goal: cut duplicate subscriptions and consolidate onto Google Workspace (which you
already pay for, per employee). Work top to bottom. Each cancellation happens only
AFTER its replacement is confirmed working — never cancel first.

Golden rule: EXPORT / MIGRATE → VERIFY → then CANCEL. Never the other way round.

---

## 1. Dropbox → Google Drive (saves the Dropbox fee)

Drive (included in Workspace) does everything Dropbox does. You're paying for both.

Steps:
1. Install **Google Drive for desktop** on the M5 (`brew install --cask google-drive`),
   sign in with your Workspace account.
2. Move all Dropbox files into Drive:
   - Easiest: open both folders in Finder, drag everything from Dropbox into a Drive
     folder. Let it fully sync (watch the Drive menu-bar icon say "up to date").
   - Decide structure as you go — ideally into a **Shared Drive** (see §4) if the
     files are business/job files, or My Drive if personal.
3. VERIFY: spot-check that files actually opened from Drive, on both the Mac and
   drive.google.com. Open a few of the important ones.
4. Only then: cancel Dropbox (dropbox.com → account → plan → cancel). Uninstall the
   Dropbox app. Do NOT install Dropbox on the M5.

Watch out for: Dropbox "online-only" files that aren't downloaded locally — make sure
they're actually pulled down before you drag, or you'll copy empty placeholders.

---

## 2. Microsoft 365 → Google Sheets/Docs (saves the 365 fee)

You're a light spreadsheet user; Sheets covers it, and you pay for it via Workspace.

Steps:
1. Find any Excel/Word files you actually care about (likely a few financial
   spreadsheets). They're probably already going into Drive via §1.
2. Open the key ones in Google Sheets/Docs (Drive converts them) and check formulas
   still work. The financial models translate fine.
3. VERIFY the important spreadsheets behave in Sheets.
4. Cancel Microsoft 365 (account.microsoft.com → Services & subscriptions → cancel).
   Don't install Office on the M5.

Safety net: if a specific spreadsheet ever truly needs real Excel, you'll have it on
the Windows 11 VM in Parallels anyway — so you're not fully losing Excel access.

Keep 365 ONLY if you discover heavy Excel use (macros, big pivots) — you don't think
you do, so default to cancelling.

---

## 3. Google Workspace seat audit (stop paying for seats you don't need)

Workspace bills per user. Some "users" may really just be forwarding addresses.

Steps (Admin console → admin.google.com):
1. List every paid user seat.
2. For each, decide: is this a REAL person who needs their own inbox/login, or is it
   an address like info@ / accounts@ / quotes@ that just needs to receive mail?
   - Real person → keep the seat.
   - Forwarding-style address → convert to a **Group** (free) or an **alias** on an
     existing account (free), then remove the paid seat.
3. The lads' seats: currently justified IF you use them for company email + the Shared
   Drive photo workflow. If a lad ONLY needs them to log into TSheets, that seat's days
   are numbered (see §5) — TSheets works with any email, not just Workspace.

Note: don't delete a user seat until you've migrated any of their important Drive/email
data and set up forwarding so mail to that address isn't lost.

---

## 4. Set up the Shared Drive + job-photo workflow (the upgrade)

This is the "do it properly" step that makes the seats you DO keep worth it.

Steps:
1. Admin console / Drive → create a **Shared Drive** (owned by the company, not you).
2. Structure, e.g.:
   - **Jobs** → one folder per job (`2026 — Smith, St Helier rewire`) → subfolders
     Photos / Certificates / Quotes / Supplier invoices
   - **Company** → insurance, NAPIT docs, templates
   - **Accounts** → supplier statements, the TSheets archive (§5)
3. Add employees to the Shared Drive.
4. Lads install the **Google Drive app on their phones** (Workspace login) → on site,
   open the job's Photos folder → upload. Photos land organised by job, owned by the
   business, visible to you instantly. No more WhatsApp photo chains.

---

## 5. TSheets → GoZappify timesheet PWA (the big recurring saving — LATER)

This is the largest duplicate cost but it's NOT a "this week" job — it depends on
building the timesheet PWA (see TIMESHEET_SPEC.md), which comes AFTER the Sprint A
security fixes.

When the PWA is ready, the cutover (full detail in TIMESHEET_SPEC.md):
1. EXPORT all historical TSheets data to CSV first → archive in Shared Drive
   (Accounts/TSheets archive). You're legally required to keep hours/pay records, so
   this archive is non-negotiable. Do this export NOW even before cancelling — it's
   free and protects the data regardless.
2. Parallel-run one pay period (TSheets + PWA), compare totals.
3. Confirm payroll handoff is covered by the export.
4. Cancel TSheets.
5. THEN revisit the Workspace seats (§3) — once TSheets no longer needs employee
   emails, some seats may become cuttable.

---

## Security housekeeping while you're in the admin console

- Turn on **2-step verification** for all Workspace users (Admin → Security). Given the
  credentials this business handles, this matters.
- Get a **password manager** (1Password / Bitwarden) for the pile of logins (GitHub,
  Railway, PayPal, QuickBooks, Workspace, trade accounts).

---

## Suggested order (so nothing breaks)

1. Install Google Drive desktop on M5.
2. Migrate Dropbox → Drive, verify, cancel Dropbox.
3. Move key spreadsheets to Sheets, verify, cancel Microsoft 365.
4. Set up Shared Drive + get the lads uploading job photos.
5. Audit Workspace seats (convert forwarding addresses to Groups/aliases).
6. Export TSheets history to CSV now (archive it) — actual TSheets cancellation waits
   for the PWA.
7. Turn on 2FA, set up a password manager.

Recurring savings unlocked: Dropbox + Microsoft 365 now; surplus Workspace seats soon;
TSheets once the PWA ships. All money currently spent doing things Workspace (or your
own product) already does.
