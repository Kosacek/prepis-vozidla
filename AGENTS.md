# AGENTS.md — prepis_vozidla_app (žádosti + evidence)

Instructions for every coding agent working in this repo (Codex, Claude, …).
App-specific details live in `prepis_app/CLAUDE.md` (zadosti.spznaklic.cz) and
`ukony_tracker/CLAUDE.md` (evidence.spznaklic.cz). This file holds the rules
that apply to both.

## "Co je nového" popup on every user-visible update

David's standing rule (2026-10-11), same as on hunter.spznaklic.cz: every
update that changes something people **see or do** ships with a one-time
"what's new" popup in Czech. The reference he approved is
`docs/whats-new/reference_hunter_intro.html` (Hunter's live-sync intro).
Copy its structure, spacing, motion and behaviour, then adapt the content and
the colour tokens to the app you're in.

### When
- Yes: new features, changed gestures/flows/screens, anything a user would
  otherwise have to discover or be told about.
- No: invisible fixes, refactors, performance, copy tweaks.
- One popup per deploy. Several changes → one popup covering the most
  important (two at most, one line each).

### Look
- Centered card (max-width 380px, radius 16px) on the app's modal scrim, in
  the app's own dialog style; colours only from the app's tokens (light + dark).
- Top: a small looping CSS-only demo (~4s) that **shows** the change, built
  from miniature copies of the app's real UI.
- Title: one short sentence, what changed, in user terms.
- Body: at most two short sentences, what it means for them.
- One full-width primary button: "Rozumím". Also closes on scrim tap / Esc.
- `prefers-reduced-motion`: no animation, show the demo's end state.

### Behaviour
- Once per device per release: `localStorage` key `<app>_whatsnew_<slug>`,
  set when shown. No storage → don't show (never on every load).
- Only on a logged-in, settled page; never on login, never over another
  dialog or mid-gesture (defer and retry).
- A new release replaces the previous popup.

### Czech copy
Natural Czech, full diacritics, informal "ty". Short — if it needs a third
sentence, the demo isn't doing its job.

### Companion: "Nová verze aplikace · Obnovit" bar
The popup only reaches pages that load the new code. Each app also needs
Hunter's update bar: pages poll a tiny endpoint returning the running build
(a hash of the app's source, computed once at startup); a page stamped with an
older build shows an inverted pill at the top, "Nová verze aplikace" +
"Obnovit" (reloads). Add it the first time an app gets a popup.

### Before deploying
Screenshot it at 375px width in light and dark (demo mid-animation) and send
it to David; confirm it shows once, stays dismissed after reload, and never
appears logged-out.
