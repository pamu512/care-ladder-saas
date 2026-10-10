# Care Ladder · Family Chat-First Runtime + Console: Implementation Plan

**For:** coding agent · **From:** design review · **Date:** 2026-09-29
**Status:** approved direction: implement in phase order
**References:**
- Facility design guide: `mockups/care-ladder-design-guide.html` (sections F1–F3 are this plan's design contract)
- Family console mockup v2 (setup + archive): `mockups/family-console.html`
- Chat runtime mockup: `mockups/family-chat-runtime.html`
- Existing code: `src/care_ladder/channels/{router,ack,notify}.py`, `ladder/orchestrator.py`, `api/app.py`, static consoles

---

## 0 · Product decision being implemented

The family member will not sit in the console. They set the household up once and live in
**WhatsApp / Telegram**. Therefore:

1. The **chat thread is the runtime**: inform → acknowledge → update → close all happen in chat.
2. The **console is setup + archive**: pairing, care-plan facts, day timeline review, clips, billing.
3. The existing signed-token ack page (`GET /ack/{token}`) stays as the universal fallback that works on any channel.
4. Every hop of every conversation is written to the incident audit trail: the same trail the facility drill-down reads.

Nothing in this plan touches the facility console (separate track, already underway).

---

## 1 · Phase plan (ship order matters)

| Phase | Delivers | Why first |
|---|---|---|
| **P1 · Conversation core** | Bot thread model, Telegram adapter v2 (free-form + inline buttons), ack-from-chat into the registry, audit events with timestamps | Telegram needs no template approval: full experience ships immediately |
| **P2 · WhatsApp path** | WhatsApp adapter v2 (UTILITY template + ack-link fallback), template management notes, numbered-reply parser | WhatsApp lands as soon as Meta approves the template |
| **P3 · Console re-roll** | Home console → family v2 (chat strip, hero, day feed, rails, pairing surface) | Depends on P1 runtime existing to mirror |
| **P4 · Commands & rhythm** | /status /pause /resume /contacts /quiet, daily receipts + evening recap | Polish after the alert path is proven |
| **P5 · Docs & tests** | README family section, env vars, honesty notes | Keep the repo's honesty convention |

Each phase lands green (full suite) and deployable on its own.

---

## 2 · P1 · Conversation core

### 2.1 New module `src/care_ladder/channels/bot.py`

Owns per-household bot threads and the conversation FSM. No UI.

```
BotThread:
  household_id, channel ("telegram"|"whatsapp"), chat_ref, members[]
  state: idle | speaker_window | family_paged | pressure | calling_N | closed
  timers: page_at, pressure_at, deadline, call_deadline_N
```

**FSM (mirrors design guide F3):**

```
cue → speaker_window ( Mom asked; reply resolves, family never paged )
speaker_window expires → family_paged:
    send inform card (frame thumb, cue text, countdown, buttons)
    ack sources: chat button | numbered reply | ack-link   (first wins)
family_paged at t-3:00 → pressure: send warn message
pressure deadline → calling_1: place voice call to contact 1 (stub ok in demo)
calling_1 no answer (window) → calling_2 ... → exhausted
ANY ack → escalation stops; case opens with owner=acker; bot asks "how did it go?"
outcome reply (free text) → case closes; documentation=reply; close card with audit line
```

**Rules:**
- One active conversation per household at a time; a new cue while open joins the same thread.
- Distress cues bypass pause and quiet hours (already true in orchestrator; keep).
- Every send/receive appends an audit event: `{tool:"bot", detail:{channel, chat_ref, message_kind, text, msg_id, at}}`.

### 2.2 Telegram adapter v2 (`router.py` extension)

- Poll or webhook mode behind env (`TELEGRAM_MODE=poll|hook`, default poll for the demo).
- Inline keyboard on alert cards: `[{"I'm on it. I'll call her myself":ack},{"Call Mom now":call_now},{"Can't take it. Go to {next}":pass}]`.
- Callback query → same handler as the ack-link POST.
- Daily-receipt + recap messages (P4) use plain sends.

### 2.3 Ack registry extension (`ack.py`)

- `acknowledge(token, by=..., channel="telegram"|"whatsapp"|"web"|"call", msg_ref=...)`: already mostly generic; add `msg_ref` and `origin` to the outcome for audit.
- Numbered-reply parser: in the open window, replies `1|2|3` (or button words) map to the same three actions; log as `ack_channel: chat`.

### 2.4 Orchestrator wiring

- `notify_and_await_ack` rung: when the plan's channel is `telegram_family|whatsapp_family`, the page goes through `BotThread.page(...)` instead of the plain adapter; the wait loop is unchanged (it already polls the registry).
- Voice-call rung (`calling_N`) reuses the dial stub; log per design guide ("Calling you now", "You answered. {next} was not contacted.").

### 2.5 Env + config

```
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID            (exists)
WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TO   (exists)
TELEGRAM_MODE=poll|hook   TELEGRAM_HOOK_URL
FAMILY_PLAN_PATH=configs/demo_family.yaml        (new: household contacts + cadence + channels)
```

### 2.6 Tests (TDD, repo style)

- FSM: inform→ack-in-window stops escalation; pressure fires at t-3; deadline → calling_1; call answered → case closed with docs; numbered reply ≡ button.
- Registry: chat-origin acks recorded with channel+msg_ref; first-wins across button/link/reply.
- Router: Telegram inline-keyboard payload shape; callback → ack event.
- Orchestrator: family plan routes through BotThread; audit events carry `at` timestamps.

---

## 3 · P2 · WhatsApp path

- Message send via Cloud API (`messages` endpoint, exists in router).
- **Template reality:** business-initiated alerts need an approved UTILITY template. Until approved:
  - Send the templated alert text (parameterized: name, room, countdown) + the **ack link** (signed token page already works).
  - Buttons arrive post-approval (interactive button templates / Flows).
- Numbered replies: within the 24h customer-service window, free-form replies are allowed: parse `1/2/3` there; outside it, only the link works. **Document this honestly in README** (repo convention).
- Template management: store template name in env (`WHATSAPP_UTILITY_TEMPLATE`), fail-closed to link-only if unset.

---

## 4 · P3 · Console re-roll (home → family v2)

Follow design guide **F1** exactly (tokens, zones, copy rules). Implementation notes:

- Keep the existing endpoints (`/incidents`, `/acks/pending`, frames, `/auth/*`, billing CTAs): the console reads, chat writes.
- Replace header: mark + "The {household} home · {person}'s apartment" + camera-status chip + Invite family + settings icon. **All fixture buttons move into the collapsed demo `<details>`** (bottom of page, family fixtures only).
- Chat strip (first element): bot status from a new `GET /family/runtime` (last message kind + ts, channel states); Open WhatsApp/Telegram deep links.
- Hero numbers from incidents: answered = resolved-with-positive-reply count; since-last = now − last positive reply ts; calls-this-week = dial events in window. All derivable from audit events (needs the P1 `at` stamps).
- Day feed: incidents + check-in moments merged by time; quotes from `speaker_prompt` event details; reply chips from reply_class.
- Side rails: contact ladder from the family plan YAML; household facts from plan + camera status; weekly recap computed like hero numbers.
- **Remove** the ack panel as an interactive surface; the strip mirrors chat state only. Keep `/acks/pending` reading for the mirror.
- Home console tests to update: fixture-button presence assertions move to the demo strip; `Path A` string must survive (test greps it): put "Path A · Mom answers OK" inside the demo strip labels.
- Billing CTAs (upgrade/portal) move under settings; governance strip stays.

---

## 5 · P4 · Commands & rhythm

- `/status`: camera, next check-in, ladder armed, quiet hours.
- `/pause 2h` / `/resume`: sets a pause window (suppress rhythm + non-distress cues; **distress bypasses**, message says so).
- `/contacts`: renders the ladder in order + "emergency services are never dialed automatically".
- `/quiet`: toggles evening-recap muting.
- Rhythm receipts: check-in-answered quiet messages (quoted words); evening recap at 20:00 local (check-ins x/x, calls this week, median response, next check-in, quiet hours).
- All command effects append audit events (repo convention: every state change is auditable).

---

## 6 · Acceptance criteria (per phase, all must pass)

- P1: a Telegram demo household end-to-end: cue → silence → inform card → tap "I'm on it" → escalation stopped → reply outcome → closed card with audit line; timeline shows every hop with timestamps; full suite green.
- P2: WhatsApp household receives templated alert + ack link; link ack stops escalation; numbered reply works inside 24h window; README documents template dependency.
- P3: console matches `mockups/family-console.html` at 1480/390px; hero numbers correct from demo fixtures; demo chrome collapsed; `Path A` grep survives; no ack-interactive elements outside the demo strip.
- P4: commands work in the demo thread; recap computes from real events; pause suppresses rhythm but a distress fixture still alerts.
- Cross-cutting: no em dashes in served copy; no emoji as UI icons; every new endpoint auth-scoped like existing ones; audit events carry `at`.

---

## 7 · Risks & honest limits (carry into README)

- Telegram polling in the demo process is fine; webhook mode is the production path.
- WhatsApp template approval timing is outside our control; link fallback is the contract.
- Voice calls remain stubbed (reserved NANP fiction): the FSM treats them as real hops anyway.
- Not a medical device; emergency fail-closed: the family copy must keep saying so.

---

## 8 · File map (where things land)

```
src/care_ladder/channels/bot.py            (new · FSM + thread model)
src/care_ladder/channels/router.py         (telegram v2: inline keys, callback; wa template send)
src/care_ladder/channels/ack.py            (origin/msg_ref on outcomes)
src/care_ladder/ladder/orchestrator.py     (family-channel routing through BotThread)
src/care_ladder/api/app.py                 (GET /family/runtime; webhook endpoints)
src/care_ladder/api/static/index.html      (family v2 console · guide F1)
configs/demo_family.yaml                   (household plan: contacts, cadence, channels)
tests/test_bot_fsm.py  test_family_ack_sources.py  test_telegram_router_v2.py
tests/test_family_console.py  test_family_commands.py
```
