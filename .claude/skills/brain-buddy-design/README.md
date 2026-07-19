# Brain Buddy Design System

Brain Buddy is a **thinking assistant with native GTD**. It pairs exactly four open GTD primary lists (Inbox, Next actions, Waiting for, Someday / maybe) with Projects and Tags, a thinking canvas that opens from the task workspace, and a voice **brain dump** that proposes tasks while you speak. Autonomous execution is deferred and is not part of the shipped Task lifecycle.

The interface is deliberately quiet — a calm, bright workspace where your tasks and the structure of your thinking are the hero, not the chrome around it.

This design system captures the visual language, content voice, and UI kit needed to design new surfaces for Brain Buddy that feel native to the product.

> **Contract note (2026).** Brain Buddy pivoted from a canvas-only knowledge-graph tool to tasks-first. Accepted records under `docs/decisions/` and shipped behavior outrank `Pivot Explorations`. Exploration cards may illustrate future ideas, but they are not production contracts.

## Sources

| Source | Path / Link |
|---|---|
| Original product codebase (React + TS + Tailwind + React Flow + FastAPI) | `brain_buddy/` (attached locally at DS creation, read-only) |
| Tailwind tokens | `brain_buddy/frontend/tailwind.config.ts` |
| Node color config | `brain_buddy/frontend/src/config/nodeColors.json` |
| Pivot design explorations (task shell, brain dump, AI states) | "Pivot Explorations" design project (shared canvas) |

No Figma file, logo asset, or marketing site was provided. Where visual marks are needed, we've designed placeholders consistent with the in-product vocabulary (see `assets/`). **These are our interpretations — flag for review.**

## Products

- **Brain Buddy web app** — tasks-first workspace:
  - **Task shell** — GTD sidebar (Inbox with count, Next actions, Waiting for, Someday / maybe, Projects list, Tags cloud, and a non-interactive `Weekly Review · coming later` disclosure) + a task list main pane. Top bar: logo, search, primary **Brain dump** mic button, avatar.
  - **Brain dump** — voice capture overlay (desktop) / full screen (mobile). The accepted async design uploads durable numbered chunks while recording and presents provisional task proposals. No canonical Task is created before explicit confirmation. The shipped bounded flow does not yet implement every offline, chunk, retention, or reconciliation capability in ADR-0002.
  - **Thinking canvas** — the original tree workspace (`BrainNode`s, bezier edges, zoom controls, inspector). Now opened *from a project or task* ("Think" affordance), not the app's root.
  - **Future Execution exploration** — speculative cards illustrate how an enabled run might report status. This is not shipped capability or current Task vocabulary.
  - Auth shell, modals, toast stack — carried over from the original app.
- **Mobile (iOS)** — brain dump capture + review flows exist as designs. Same visual language, 44px+ hit targets.

There is still no marketing site, pricing, or docs portal. Future surfaces should extend this visual language rather than invent a new one.

---

## Task and capture vocabulary

Accepted product contracts fix the following vocabulary. Use it verbatim; exploratory cards cannot override it.

**GTD primary lists** (sidebar order): `Inbox` → `Next actions` → `Waiting for` → `Someday / maybe`. These are exactly four open GTD primary lists. `Projects` and `Tags` are secondary organization.
- Inbox count is a sky-500 pill badge; other counts are plain slate-400 numerals.
- Weekly Review remains visibly deferred as non-interactive `coming later` status; do not invent cadence, due state, or a fifth primary list.

**Tags** use plain names such as `calls`, `errands`, `deep-work`, and `laptop`. Render them as neutral pills (white bg, slate-200 border, slate-600 text in the sidebar; slate-100 bg in task rows). Do not restore retired `@` prefixes.

**Task row anatomy** (list view): circle checkbox (18px, slate-300 border) · title (14px/500) · optional due-date chip (rose), then right-aligned Tag pill and project name (11px slate-400, right-aligned fixed column). White card, slate-200 border, radius 12px, shadow-soft; hover → shadow-raised.

**Speculative, non-shipped Execution reference.** Named agents, autonomous work, assignment semantics, lifecycle chips, and run logs in the preview cards are exploratory material only. Do not generate them in production until an accepted Execution contract authorizes the capability and its user-visible semantics. Execution remains separate from Task lifecycle: a run may reference a Task and return evidence, but it cannot add Task states or own Task completion. A successful run never completes a Task; completion requires an explicit Tasks command.

If a future accepted Execution contract enables these patterns, use emerald + Lucide `Sparkles` for run state and keep sky + Lucide `Network` for the thinking canvas. The speculative cards show named executor identities, queued/working/needs-you/review/failure chips, and chronological evidence logs solely to preserve design exploration. Revalidate every label and assignment control against the accepted contract before reuse.

**Due dates** are rose chips ("before Sat", "Sat") — rose-50 bg, rose-200 border, rose-700 text. Only for real deadlines; no decorative dates.

**Brain dump patterns**:
- Pulsing mic: sky-500 circle, expanding sky ring (`scale(1)→scale(2)` fade, 1.8s ease-smooth infinite).
- Live transcript: slate-400 text, tail of the sentence in slate-600, blinking 2px sky caret (step-end 1.1s).
- Recording indicator: 7px rose dot + mm:ss, rose-600.
- Task "forming…": dashed slate-300 border card with a slow shimmer sweep.
- Waveform: 4px sky bars, scaleY animation, staggered 150ms.
- Capture status must state that audio is recorded locally and uploaded as durable numbered chunks; never imply that stopping is the first persistence boundary.
- Authority sequence is fixed: `Provisional · N` → `Stop & review` → `Confirm N additions`.
- Privacy/authority copy: "No canonical Task is created before explicit confirmation." Working audio and operation artifacts follow the accepted retention/deletion policy.

---

## Content Fundamentals

Brain Buddy's voice is **calm, second-person, and action-oriented**. It talks to the user as a quiet collaborator — never cheerleading, never apologizing excessively. Copy tends toward _short imperatives_ paired with an _explanatory subtitle_. Product copy is **English**, sentence case.

**Tone**
- **Calm and confident.** "Start with your first undesired effect" not "Let's go! 🚀"
- **Second person.** "You" addresses the user directly; "we" only appears in neutral error recovery ("We couldn't load this tree").
- **Explain then enable.** Empty states pair a one-line headline with a plain-language hint, then a single CTA — never a wall of text.
- **Honest about errors.** Failures show a specific reason + correlation ID when available, plus a Retry affordance.
- **Automation is matter-of-fact when enabled.** Future Execution copy states what happened without personality. Do not expose run copy before an accepted contract enables it.

**Casing**
- **Sentence case everywhere.** Headings, buttons, menu items, section labels. "Send 9 to inbox", not "Send To Inbox".
- **UPPERCASE micro-labels** — only for section labels and dropdown headers (tracking-wide, 10px, e.g. "PROJECTS", "TAGS", "PROVISIONAL · 9").
- **Sparing em-dashes and ellipses** for in-progress states: "Importing…", "forming…", "Preparing export…".

**Grammar quirks**
- Uses `·` (middle dot) as inline metadata separator: `6 tasks · 1 running on AI`, `Thinking · 12 steps`.
- User concepts stay lowercase ("task", "tree", "node", "inbox", "tag") even as product nouns.
- Contractions are fine: "can't", "couldn't", "you'll".

**Emoji: never.** Do not introduce them in slides, marketing, or UI.

**Examples pulled from the product + pivot designs.** Rows describing agents or run logs are speculative, non-shipped Execution examples and are not current product copy.

| Situation | Copy |
|---|---|
| Task list meta | "6 tasks · 1 running on AI" |
| AI offer chip | "AI can draft" |
| Agent running chip | "Drafter · ready in ~5 min" |
| Agent blocked chip | "Needs you — choose a venue" |
| Run log steps | "Searched 14 sources" · "Drafted outline" · "Asked you to choose a venue" |
| Agent done | "Ready for review" |
| Thinking chip | "Thinking · 12 steps" |
| Add-task hint | "Add a next action — or dump everything on your mind with the mic above" |
| Brain dump header | "Provisional · 9" |
| Brain dump capture line | "Recording locally · 8 durable numbered chunks uploaded" |
| Stop CTA | "Stop & review" |
| Review header | "Review 9 additions" — "Edit before anything is added to your inbox" |
| Confirm CTA | "Confirm N additions" (replace `N` with the current frozen count) |
| Empty canvas heading | "Start with your first undesired effect" |
| Load error heading | "We couldn't load this tree" |
| Toast success (snapshot) | "Snapshot captured" → "Nodes +3/-0/~1, Relations +2/-0/~0" |
| Signup password hint | "At least 12 characters. Longer is better." |

**Vibe:** a thoughtful teammate leaning over your shoulder. Not a hype app.

---

## Visual Foundations

**Unchanged by the pivot.** Brain Buddy's aesthetic is a **bright, low-chroma workspace** — a sheet-of-paper canvas with a single cool accent. Tailwind `slate` neutrals + `sky-500` brand primary + `indigo-500` secondary.

### Color
- **Brand primary** `#0EA5E9` (sky-500) — all interactive accents, focus rings, the logo, primary buttons, the brain-dump mic, selection rings, inbox count badge.
- **Brand secondary** `#6366F1` (indigo-500) — secondary accents, project dot colors; used sparingly.
- **Neutrals:** slate scale (`#0F172A` → `#F8FAFC`). Body text is `slate-900` on `surface-base`.
- **Surface tokens:** `surface-base` `#F8FAFC`, `surface-sunken` `#F1F5F9`, `surface-raised` `#FFFFFF`. Three levels of depth, nothing darker.
- **Semantics:** rose-600 destructive + due dates + recording, emerald-500 success, amber-600 warnings, sky-500 info + thinking/canvas states. Emerald/amber Execution aliases are reserved speculative tokens until an accepted Execution contract enables them.
- **Node semantics:** `colors_and_type.css` defines the authoritative node-color tokens mirrored from production `nodeColors.json`: leaf (no outgoing) `#EF4444` white text, root (no incoming) `#FACC15` dark text, default white on slate-900. Preview cards must reference these tokens, never generic warning/danger aliases.

### Type
- **Family:** Inter with font-feature-settings `"cv11", "ss01", "ss03"`.
- **Scale:** `display` 28/1.15/-0.02em (empty states) · `title` 20/1.3/-0.015em (dialog + pane titles, e.g. "Next actions") · `subtitle` 15/1.4 · body 14 (UI default) · micro 11 (metadata) · 10 uppercase labels.
- **Weights:** 400/500/600/700. Body 400–500, headings 600, never heavier.
- **No serif. No monospace display.** Mono only inside diff summaries and invite codes.

### Spacing
- 4-pt base. `gap-2` (8) inside buttons/chips, `gap-3` (12) between rows, `gap-4` (16) between sections, `p-3` compact cards, `p-5` dialogs.
- GTD sidebar is **248px**; the canvas inspector panel is **320px** (`w-80`).

### Background
- **Always flat `#F8FAFC`** — no gradients, no imagery, no patterns, no noise.
- Canvas uses React Flow's dot background at `opacity: 0.85`.
- **Zero photography.** Imagery is not part of the system.

### Animation
- **Signature easing:** `cubic-bezier(0.22, 1, 0.36, 1)` (`ease-smooth`) — soft arrival, no overshoot. Durations 150–250ms.
- Ambient loops exist **only in brain dump** (mic pulse, waveform, caret blink, shimmer) — nowhere else. No bounce, no spring, no rotation flourishes.

### Hover & press states
- **Hover:** lighter bg (`hover:bg-slate-100` ghost), stronger shadow (`hover:shadow-raised` on task rows/cards), or brand-tinted border. Primary buttons hover *lighter* (`sky-400`), not darker.
- **Press:** `active:scale-[0.98]` on all buttons. No color change on press.
- **Focus-visible:** double ring — `0 0 0 2px #fff, 0 0 0 4px rgba(14,165,233,.5)`.
- **Selection:** sky-500 @ 22% with slate-900 text.

### Borders
- **`border-slate-200`** universal hairline; `border-slate-300` on hover. No dark borders.
- **Dashed borders** = empty/placeholder/forming states only (add-task affordance, forming task card, "Add date" chip).
- **Colored borders carry meaning:** emerald-200 card border = AI actively working on this item; sky-500 1.5px border = currently being edited/selected.

### Shadows (elevation)
- `shadow-soft` — rows, buttons, inputs at rest
- `shadow-raised` — hover
- `shadow-floating` — dropdowns, dialogs, toasts, top bar, brain-dump overlay
- `shadow-glow` — sky halo, selected canvas node only
- `shadow-ring-focus` — focus double-ring

### Corner radii
- 6px inputs/menu items · 8px buttons/chips-as-buttons · **10–12px task rows** · 14px mobile task cards · 20px dialogs/panels/toasts/brain-dump overlay · full for pills, badges, mic, avatars.
- **Canvas nodes stay asymmetric:** `rounded-l-2xl rounded-r-xl`.

### Transparency & blur
- Only on floating/sticky surfaces: `bg-white/90 backdrop-blur` (header, menus, toasts), `rgba(248,250,252,.8) + blur(4px)` brain-dump scrim. Never heavier than 8px blur.

### Cards
- `rounded-xl` + `border-slate-200` + white or `surface-sunken/60` + `shadow-soft`. No gradients, no colored left borders. Variant color = **background tint + border tint only** (emerald-50 AI, rose-50 danger, amber-50 warning).

### Visual tells (unmistakably Brain Buddy)
- **Asymmetric canvas-node corners** + sky accent bar.
- **Sky glow** on selected items.
- **Double-ring focus** everywhere.
- **ALL-CAPS 10px section labels** as the only uppercase.
- **The pulsing sky mic** — the brain dump entry point, always visible in the top bar.
- **Future-only:** emerald Sparkles chips + squircle executor avatars are speculative Execution exploration, not a shipped product tell.

---

## Iconography

**[Lucide](https://lucide.dev)** only — stroke-based, 1.5–2px stroke, 24×24 viewbox, rounded caps. Rendered 16px in buttons/rows, 20px next to headings, 28px in circular badges. Color inherits (`currentColor`); rest state slate-500/600, brand slots sky-500.

**Core icons post-pivot:** `Mic` (brain dump), `Square` (stop recording), `Inbox`, `ArrowRight` (next actions), `Clock` (waiting for), `Archive` (someday), `Search`, `Network` (thinking canvas), `Calendar`, `Trash2`, `Plus`, `X`, `ChevronDown`, `ChevronRight`, `ArrowDownUp` (sort). Canvas set carried over: `Sprout`, `Minus`, `Maximize2`, `AlertTriangle`, `CheckCircle2`, `Info`, `LogOut`, `Download`, `Upload`, `Pencil`, `Save`, `History`, `Layers`, `ShieldCheck`, `Tag`. `RotateCcw` for Weekly Review and `Sparkles` for Execution remain deferred.

No custom SVG illustration, no emoji, no icon fonts. If a symbol is missing, pick the closest Lucide match — never mix libraries. The exported Sprout logo files are the only branded-asset exception.

### Logo mark
Lucide `Sprout` doubles as the product logo (top bar). `assets/logo.svg` and `assets/logo-lockup.svg` are the authoritative logo sources for every generated design; reference those files directly and do not redraw, reinterpret, or add alternate marks.

---

## Index

### Root
- `README.md` — you are here
- `SKILL.md` — agent skill descriptor (usable by Claude Code)
- `colors_and_type.css` — CSS variables for colors + type primitives + semantic tokens (incl. AI-state aliases)
- `assets/` — logo, wordmark
- `preview/` — design-system cards for each token set and component cluster
- `ui_kits/workspace/` — Brain Buddy canvas-workspace UI kit (React JSX, interactive demo)
- `_ds_bundle.js` — generated artifact; do not edit by hand or import into production code

### UI kits
- `ui_kits/workspace/` — the **pre-pivot** canvas app: auth, top bar, canvas with `BrainNode`s, inspector, modals, toasts. Still valid for the thinking-canvas surface, which now opens from a task. A tasks-first shell kit is not built yet — use the task-row/GTD preview cards + Pivot Explorations as reference.

### Notes for iterators
- Everything visual derives from production code + the Pivot Explorations; there is no Figma.
- Contract-correct GTD and voice guidance in this README may guide implementation; exploratory named-agent, assignment, autonomous-run, and run-log cards remain speculative and non-shipped.
- `Sprout`-as-logo is pragmatic; a real brand mark may exist.
- Font delivery via Google Fonts import in `colors_and_type.css`.

---

## Syncing this skill

This directory originated from the "Brain Buddy Design System" project on claude.ai/design (project id `ade33f3b-852a-4b58-ae75-256156754f68`) via the `DesignSync` tool. Accepted repository contracts take precedence over remote design content, so never overwrite contract corrections with a blind pull.

`ui_kits/workspace/app.jsx` and `ui_kits/workspace/components.jsx` are editable sources. `_ds_bundle.js` is a duplicated generated artifact; do not edit it directly. After either source changes, use `DesignSync` against the same project to Regenerate `_ds_bundle.js`, then verify the metadata header's `sourceHashes` before commit. Each value is the lowercase 12-character SHA-256 prefix of the exact UTF-8 source bytes. This command prints the expected values:

```bash
python3 -c 'import hashlib,pathlib; root=pathlib.Path(".claude/skills/brain-buddy-design"); [print(p, hashlib.sha256((root/p).read_bytes()).hexdigest()[:12]) for p in ("ui_kits/workspace/app.jsx", "ui_kits/workspace/components.jsx")]'
```

Run `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py -v` after regeneration. The test fails if a recorded hash differs, the manifest points to a missing card, or accepted design contracts drift.
