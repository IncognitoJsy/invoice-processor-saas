# GoZappify — Launch Readiness Checklist

Goal: 100% working, out-of-the-box product before spending a penny on marketing.
Work top to bottom — sections are ordered by what kills launches first.
Mark items `[x]` as done. "Done" means tested, not just built.

---

## 0. Foundation (do first)

- [ ] CLAUDE.md in repo, verified by Claude Code against actual codebase
- [ ] Phase 1 audit complete — AUDIT.md merged to staging
- [ ] Top 10 risks from audit triaged: each one fixed, scheduled, or consciously accepted
- [ ] Money maths verified: all currency calcs use Decimal, rounding consistent end-to-end
- [ ] Extraction test harness built: 30–50 real supplier invoices (CEF, Rexel, Screwfix,
      small wholesalers, scanned/photographed ones) with measured accuracy score
- [ ] Extraction accuracy ≥ target you're happy to put your name on (write it here: ____%)

## 1. The first 10 minutes (new-user experience)

- [ ] Full stranger-test completed: fresh account → connect QBO → upload invoice → result,
      with zero prior knowledge. Every confusing moment logged and fixed
- [ ] Repeat stranger-test for the Xero path
- [ ] Repeat for "no accounting software — send invoice direct to customer" path
- [ ] Empty states designed: dashboard, invoices, bills, reports all look intentional with no data
- [ ] Instant demo: new user can process a sample invoice and see the result BEFORE
      connecting QuickBooks/Xero or entering payment details
- [ ] Onboarding prompts: after signup, the app tells the user the next step at every stage
- [ ] Signup → first processed invoice possible in under 5 minutes
- [ ] Tested on a phone — trades users live on their phones

## 2. Billing edge cases (PayPal)

- [ ] Renewal payment fails → user sees clear message, grace period defined, access rules decided
- [ ] User cancels → access until period end, data retained per your policy, can resubscribe cleanly
- [ ] Upgrade tier mid-cycle → works, proration behaviour decided and tested
- [ ] Downgrade tier → works, feature access adjusts correctly
- [ ] Annual tiers tested end-to-end
- [ ] Webhook failure handling: if PayPal webhook doesn't arrive, system reconciles (no user
      stuck paying-but-locked-out, none using free-forever)
- [ ] Refund process decided and written down (even if manual)
- [ ] Pricing page matches actual billing amounts exactly — homepage inconsistencies FIXED

## 3. Failure handling (what users see when things break)

- [ ] Extraction fails on an invoice → friendly message + manual-entry fallback or retry path
- [ ] QuickBooks token expired → user prompted to reconnect, nothing silently lost
- [ ] Xero sync error → visible status, retry button, clear explanation
- [ ] Gmail connection drops → detected and surfaced
- [ ] File upload errors (huge file, wrong format, corrupt PDF) → handled gracefully
- [ ] No raw 500 pages anywhere a user can reach — custom error page with support contact
- [ ] Every failed sync/extraction visible in a status list (user never wonders "did it work?")

## 4. Monitoring & ops (know before they do)

- [ ] Error tracking live (e.g. Sentry free tier) on production
- [ ] Uptime monitoring on homepage, app login, and API endpoints
- [ ] Telegram alert to you on: extraction failure spike, payment webhook failure, app down
- [ ] Railway Postgres backups confirmed — and ONE RESTORE ACTUALLY TESTED
- [ ] Staging environment mirrors production config (env vars audited)
- [ ] Deploy process written down: exactly how a change goes staging → production, and how
      to roll back in under 5 minutes

## 5. Trust, legal & support

- [ ] Terms of Service published
- [ ] Privacy Policy published (covers financial data, AI processing of invoices, Gmail access)
- [ ] GDPR/data-protection basics: data export on request, deletion on request, processor
      list (Anthropic, Railway, PayPal, Google) documented
- [ ] Support email live, tested, lands in an inbox you check — reply-time goal: same day
- [ ] Data security one-pager you can send when a customer asks "is my data safe?"
- [ ] SSL/security headers checked on gozappify.com

## 6. QuickBooks App Store

- [ ] OAuth connect flow flawless (the review will test it)
- [ ] Disconnect flow flawless (the review will test this too)
- [ ] Intuit review call completed
- [ ] Listing copy + screenshots polished — this is a marketing channel, treat it like one

## 7. Help content

- [ ] Connecting QuickBooks (article or 60-sec video)
- [ ] Connecting Xero
- [ ] Uploading & processing your first invoice
- [ ] Setting your markup
- [ ] Sending an invoice to a customer
- [ ] Fixing a failed sync
- [ ] Help content linked from inside the app at the relevant moments

## 8. Soft launch (before paid marketing)

- [ ] 5–10 real trades contacts (Jersey/UK) using it on real invoices
- [ ] Watched at least 2 of them onboard live (in person or screen share) — notes taken
- [ ] Their confusion points fixed
- [ ] At least 3 would genuinely be annoyed if you took it away (ask them)
- [ ] One testimonial/quote secured for the homepage
- [ ] Monthly value summary working: "GoZappify saved you X hours / caught £Y in price
      rises" — the retention engine

---

## Explicitly NOT before launch (parked)

- Voice to Quote revival
- Employee timesheet PWA
- Price-creep intelligence v1 (start AFTER soft launch validates the core — it's the
  retention moat, not the acquisition hook)
- Any new modules

## Launch gate

Marketing spend starts only when sections 0–7 are fully checked and section 8 shows
real tradespeople succeeding without your help. That's "ready out of the box."
