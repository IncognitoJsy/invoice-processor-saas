# LAUNCH BLOCKER — Google OAuth verification (Gmail invoice-fetching)

## The problem
The Gmail invoice-fetching feature uses Google OAuth with **sensitive/restricted
scopes** (reading email). The Google Cloud project is currently **unverified /
in Testing**, which means:

1. **Scary warning at sign-up** — users see "Google hasn't verified this app...
   you shouldn't use it" and must click Advanced → Proceed. Most real users will
   bail at this screen. Lost customers at the worst moment (onboarding).
2. **Hard scale cap** — unverified apps with sensitive scopes are limited to
   ~100 users total, and refresh tokens can expire every 7 days (connections keep
   breaking). For a product targeting hundreds-to-thousands of users, this is a
   hard ceiling on the email-fetching feature.

This is a **launch blocker for email-fetching at scale**, not just cosmetic.

## Important: developer account ownership
The Google Cloud project / OAuth consent screen is currently owned by
**rudiholzmeier23@gmail.com** (personal Gmail — same as the reCAPTCHA key owner).
For a business verification submission, ideally move/own this under the business
identity (proton.je Workspace) BEFORE submitting — moving it later is painful.
Decide this first.

## What verification involves (Google OAuth app verification)
Because of the Gmail scopes, this is a review process, not a toggle:
- Verified domain — gozappify.com ✓ (already owned)
- Published privacy policy URL and terms of service URL (likely already have)
- OAuth consent screen fully filled out (app name, logo, support email, scopes
  justification)
- A demo video showing exactly how the app uses the Gmail data
- Written justification for why each sensitive scope is needed
- **Check the scope tier:** "sensitive" scopes need standard verification;
  "restricted" scopes (full Gmail read) may additionally require a paid
  third-party security assessment (CASA) — slow and potentially expensive.
  → ACTION: confirm exactly which Gmail scope the app requests. If a narrower
    scope (e.g. gmail.readonly on specific metadata, or a more limited scope)
    avoids the "restricted" tier, that dramatically simplifies verification.

## Why start early
Google's review can take **weeks**. Identify and start it well before launch,
not the week of. The third-party security assessment (if required) can take
months and cost money, so finding out the scope tier early is the single most
important step.

## Suggested order
1. Decide developer-account ownership (personal Gmail → business Workspace?).
2. Confirm exactly which Gmail scope(s) the app requests (sensitive vs restricted).
   This determines whether you need the expensive security assessment.
3. If on a restricted scope, investigate whether a narrower scope meets the need.
4. Fill out the OAuth consent screen fully; ensure privacy policy + terms URLs live.
5. Record a demo video; write scope justifications.
6. Submit for verification; expect weeks.

## Interim (pre-verification)
- You and any early test users can still use it via Advanced → Proceed (you've
  done this).
- Keep total Gmail-connected users under ~100 until verified.
- Don't market the email-fetching feature heavily until verification clears,
  to avoid users hitting the warning at scale.

---

## IMPORTANT SEQUENCING — don't submit verification too early

GoZappify is not yet an official business. The plan (correct) is: when it
officially starts, give it its OWN Google Workspace (e.g. a gozappify.com
Workspace), separate from proton.je (the electrical business), and move
GoZappify's business-critical accounts off the personal Gmail
(rudiholzmeier23@gmail.com) onto that.

The trap: the Google Cloud project (OAuth consent screen + verification) is
currently owned by the personal Gmail. **Transferring a Cloud project between
accounts — especially one mid-verification or already verified — is painful and
can reset verification progress.** So do NOT submit OAuth verification while the
project is owned by the personal Gmail if you intend to move it to a business
Workspace later — you risk redoing weeks of verification work.

Correct order when GoZappify becomes official:
1. Create the gozappify.com Google Workspace.
2. Create (or move) the Google Cloud project under that Workspace identity.
3. THEN submit OAuth verification — owned by the business from day one.
4. Also move the reCAPTCHA key ownership to the business Workspace at the same time.

Until then (pre-official, just Rudi + a few early testers):
- Leave OAuth on the personal Gmail; it works for testing via Advanced → Proceed.
- Stay under ~100 Gmail-connected users.
- Do NOT submit verification yet.

So the FIRST domino is not "submit to Google" — it's "decide when GoZappify
officially becomes a business and gets its Workspace." OAuth verification,
project ownership, and reCAPTCHA ownership all hang off that.
