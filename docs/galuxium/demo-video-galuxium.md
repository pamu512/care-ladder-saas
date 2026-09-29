# Care Ladder - Galuxium Nexus V2 Demo Video Script (SaaS cut)

**Target: 3:30-4:00.** Standalone Galuxium cut, adapted from the OpenCV
production script (`docs/demo-video-script.md` - do not modify that file; it
is the record of a finished video). This cut adds the tenancy, facility, and
billing story and drops the AWS deep-dive (that is the upstream filing's
story).

Word-for-word VO in the right column - paced ~135 wpm to the on-screen
action.

## Pre-record setup

1. Serve the SaaS fork locally: `cd ~/Documents/GitHub/care-ladder-saas && uvicorn care_ladder.api.app:app --port 8000`.
2. Tabs: `http://localhost:8000/` (landing), `/ui/` console. Editor: `configs/demo_facility.yaml`.
3. Record 1440p+, browser zoom ~125%, full-screen browser.
4. Facility beat needs the notify and supervisor rows readable without VO -
   zoom the timeline when they land (mute-test note).

## Shot list + VO

| # | Time | On screen (action) | VO (read verbatim) |
| --- | --- | --- | --- |
| 1 | 0:00-0:18 | Landing page at `/` - hero, then scroll pricing | "Care Ladder is a wellness ladder for the camera era: vision spots the moment, and a confirm-before-escalate ladder picks the next human-safe step. Hosted, multi-tenant, and priced per household - Home at twenty-nine a month, Facility Starter at one-ninety-nine, Facility Growth at four-ninety-nine." |
| 2 | 0:18-0:40 | Landing demo panel - click **Sign in to Home demo**, console loads with **Home** badge | "Two one-click demo accounts on the landing page. This one is a family home: one camera, one monitored person, and a ladder that texts before it ever thinks about calling. Notice the badge - this tenant is in home mode." |
| 3 | 0:40-1:10 | `/ui/` - click **Path A** fixture; timeline builds check-in → OK resolve | "The core loop is unchanged from the OpenCV build, because it works. A stillness cue fires. The ladder looks again, asks out loud - are you okay? - and a verbal okay resolves it. No call, no alert, everything on the audit trail. Every rung the agent considered is timestamped." |
| 4 | 1:10-1:40 | Click **Path B**; timeline lands dial-primary → dial-secondary → jump row | "Silence this time. No answer means advance: dial the primary, log the miss, dial the secondary, resolved. The jump event shows the reasoning, not just the outcome - the ladder noticed the wait window was already consumed and said so." |
| 5b | 1:40-2:20 | Sign out → **Sign in to Facility demo** → **Facility** mode badge → run **Facility · notify → supervisor** fixture; zoom timeline: `notify_channel` (adapter: stub/slack) → `notify_supervisor` (Floor Lead) → dial row | "Now the wedge: assisted living. Same camera cue, but the ladder is leaner ops. After check-in silence, operations get a Slack ping. Then the floor lead is escalated - a human whose actual job is to walk down the hall. Only then does the primary caregiver's phone ring. Still confirm-before-escalate. Still no live emergency calling. Still not a medical diagnosis. And every row is readable on the timeline even with the sound off." |
| 6 | 2:20-2:50 | Editor: `configs/demo_facility.yaml` - notify_channel + notify_supervisor rungs; toggle a comment | "Facility behavior is config, not code - the same YAML schema as home, with two extra rungs. A five-room operator edits a file instead of buying an integration. That is the whole wedge: the audit trail facility auditors already want, on pricing a small home can actually pay." |
| 7 | 2:50-3:20 | Scroll the audit trail; open an incident's silhouette clip panel | "Multi-tenancy is enforced at the store layer: every query carries a tenant id, and clip frames stay silhouettes - blur happens before storage, in every tenant. The audit trail is the product: who knew what, when, and what the ladder did about it." |
| 8 | 3:20-3:45 | Billing: console plan badge → **Upgrade** → Stripe test checkout page; back to console, badge flips | "Upgrades run through Stripe Checkout in test mode, and the webhook is fail-closed - an unsigned webhook is rejected, never trusted. Plan gates flip in the console the moment the session completes." |
| 9 | 3:45-4:00 | End card: repo URL + landing URL; honesty notes on screen | "Deployed on Render with managed Postgres, seeded idempotently on boot. The honest parts are written down: dialing is stubbed to reserved five-five-five numbers, emergency calling ships disabled behind a human gate, and this is a wellness workflow - not a medical device. Care Ladder: confirm before you escalate." |

## Cut-in cheatsheet

- Stripe checkout: test mode, use `4242 4242 4242 4242` - never show real keys.
- The facility beat (5b) is the differentiator; if time-boxed, keep it and cut shot 6.
- Mute test: facility notify → supervisor rows must read clearly with VO muted.
- Numbers to say exactly: **$9 / $49 / $99 · two demo accounts · fail-closed webhook**.

## Attribution

- Engine and Path A/B fixtures: Care Ladder upstream (OpenCV AI Competition 2026 build).
- Music/footage: none required; all on-screen action is the live product.
