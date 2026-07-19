# Brain Buddy Design System

Brain Buddy is a **thinking assistant + AI task tracker**. It pairs a GTD-style task system (Inbox, Next actions, Waiting for, Someday, projects, contexts) with a chain-of-thought canvas (5 whys, CRT-style trees) that opens *from a task*, plus a voice **brain dump** that extracts tasks live as you speak. AI is a first-class executor: it can take a task (draft a post, research an option) and report back for your review.

The interface is deliberately quiet — a calm, bright workspace where your tasks and the structure of your thinking are the hero, not the chrome around it.

This design system captures the visual language, content voice, and UI kit needed to design new surfaces for Brain Buddy that feel native to the product.

> **Pivot note (2026).** Brain Buddy pivoted from a canvas-only knowledge-graph tool to tasks-first. The task shell, brain dump, and AI-executor patterns below are established in `Pivot Explorations` (design work, options 1a/1c/1d/1e); the canvas patterns are carried over from the original production code. Where they conflict, the pivot direction wins.

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
  - **Task shell** — GTD sidebar (Inbox with count, Next actions, Waiting for, Someday / maybe, Weekly review, Projects list, Contexts tag cloud) + a task list main pane. Top bar: logo, search ("Search tasks and trees"), primary **Brain dump** mic button, avatar.
  - **Brain dump** — voice capture overlay (desktop) / full screen (mobile). Live transcription strip + tasks extracted on the fly; nothing is saved until you stop. Followed by a **review** step where you edit extracted tasks before they land in the inbox.
  - **Thinking canvas** — the original tree workspace (`BrainNode`s, bezier edges, zoom controls, inspector). Now opened *from a project or task* ("Think" affordance), not the app's root.
  - **AI executor** — AI takes suitable tasks and reports status inline in the task row.
  - Auth shell, modals, toast stack — carried over from the original app.
- **Mobile (iOS)** — brain dump capture + review flows exist as designs. Same visual language, 44px+ hit targets.

There is still no marketing site, pricing, or docs portal. Future surfaces should extend this visual language rather than invent a new one.

---

## Task & AI vocabulary

The pivot introduces a fixed vocabulary. Use it verbatim — don't invent synonyms.

**GTD lists** (sidebar order): `Inbox` → `Next actions` → `Waiting for` → `Someday / maybe` → `Weekly review`, then `Projects`, then `Contexts`.
- Inbox count is a sky-500 pill badge; other counts are plain slate-400 numerals.
- Weekly review gets an amber "due Sun"-style chip when due.

**Contexts** are lowercase `@tags`: `@calls`, `@errands`, `@deep-work`, `@laptop`. Rendered as neutral pills (white bg, slate-200 border, slate-600 text in sidebar; slate-100 bg in task rows).

**Task row anatomy** (list view): circle checkbox (18px, slate-300 border) · title (14px/500) · optional chips in order: due date (rose), AI status (emerald/sky), then right-aligned: context pill, project name (11px slate-400, right-aligned fixed column). White card, slate-200 border, radius 12px, shadow-soft; hover → shadow-raised.

**AI states** — two distinct meanings, two colors:
- **Agent executing a task** → emerald family + Lucide `Sparkles`. Chip copy patterns: "AI can draft" (offer), "Drafter · ready in ~5 min" (running, agent name + ETA), "Ready for review" (done). A task with active agent work gets an emerald-200 card border.
- **Thinking canvas attached/running** → sky/info family + Lucide `Network`. Chip copy: "Thinking · 12 steps". Also the sidebar "Think" affordance on projects.
- Never mix: emerald = an agent does the work, sky = the canvas/thinking layer.
- Agents never act silently: work is offered ("AI can draft"), then visibly running with a live run log, then reviewed by the human. Checkbox stays human-only — agent work ends in "review", not "done".

**Agents** are named executors. A task is assigned to an agent the same way it would be to a person — the agent shows in the assignee slot.
- **Agent identity:** a name (sentence case, role-like: `Drafter`, `Researcher`, `Scheduler`) + a **squircle avatar** — 8px-radius rounded square, emerald-50 bg, emerald-700 Sparkles glyph. Humans keep **circle** avatars (sky-100/sky-700 initials). The circle-vs-squircle distinction is the load-bearing tell; never give an agent a circle.
- **Agent lifecycle** (status chips, in order): `Queued` (slate neutral) → `Working — step 4 of 9` or `· ready in ~5 min` (emerald, pulsing 6px dot) → `Needs you` (amber — blocked on a manual action) → `Ready for review` (emerald, check). Terminal failure → rose "Couldn't finish" + reason.
- **`Needs you` is the loudest agent state.** Amber chip + amber-50 row tint. It always names the concrete manual action and offers 1–2 buttons inline ("Connect account", "Choose one", "Approve send"). Agent work never silently stalls.
- **Run log**: every agent task exposes a chronological log (drawer/inspector section, label "RUN LOG"). Step anatomy: 6px status dot (emerald done · pulsing emerald current · amber needs-you · slate upcoming) · step text 13px · timestamp 11px slate-400 right-aligned. Manual-action requests and the human's responses appear inline in the log as amber cards, so the trail reads as one conversation. Artifacts the agent produced ("Draft v2") are white chip-cards linked from the step.
- **Attribution copy** is matter-of-fact and past-tense in logs: "Searched 14 sources", "Drafted outline", "Asked you to choose a venue". No first person, no personality.

**Due dates** are rose chips ("before Sat", "Sat") — rose-50 bg, rose-200 border, rose-700 text. Only for real deadlines; no decorative dates.

**Brain dump patterns**:
- Pulsing mic: sky-500 circle, expanding sky ring (`scale(1)→scale(2)` fade, 1.8s ease-smooth infinite).
- Live transcript: slate-400 text, tail of the sentence in slate-600, blinking 2px sky caret (step-end 1.1s).
- Recording indicator: 7px rose dot + mm:ss, rose-600.
- Task "forming…": dashed slate-300 border card with a slow shimmer sweep.
- Waveform: 4px sky bars, scaleY animation, staggered 150ms.
- Safety copy: "Nothing is saved until you stop."

---

## Content Fundamentals

Brain Buddy's voice is **calm, second-person, and action-oriented**. It talks to the user as a quiet collaborator — never cheerleading, never apologizing excessively. Copy tends toward _short imperatives_ paired with an _explanatory subtitle_. Product copy is **English**, sentence case.

**Tone**
- **Calm and confident.** "Start with your first undesired effect" not "Let's go! 🚀"
- **Second person.** "You" addresses the user directly; "we" only appears in neutral error recovery ("We couldn't load this tree").
- **Explain then enable.** Empty states pair a one-line headline with a plain-language hint, then a single CTA — never a wall of text.
- **Honest about errors.** Failures show a specific reason + correlation ID when available, plus a Retry affordance.
- **AI is matter-of-fact.** Status chips state what's happening and when it's done ("AI drafting — ready in ~5 min"). No personality, no "I'm on it!".

**Casing**
- **Sentence case everywhere.** Headings, buttons, menu items, section labels. "Send 9 to inbox", not "Send To Inbox".
- **UPPERCASE micro-labels** — only for section labels and dropdown headers (tracking-wide, 10px, e.g. "PROJECTS", "CONTEXTS", "HEADED TO INBOX · 9").
- **Sparing em-dashes and ellipses** for in-progress states: "Importing…", "forming…", "Preparing export…".

**Grammar quirks**
- Uses `·` (middle dot) as inline metadata separator: `6 tasks · 1 running on AI`, `Thinking · 12 steps`.
- User concepts stay lowercase ("task", "tree", "node", "inbox", "context") even as product nouns.
- Contractions are fine: "can't", "couldn't", "you'll".

**Emoji: never.** Do not introduce them in slides, marketing, or UI.

**Examples pulled from the product + pivot designs**

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
| Brain dump header | "Brain dump · 9 tasks captured" |
| Brain dump safety line | "Nothing is saved until you stop" |
| Stop CTA | "Stop & send 9 to inbox" |
| Review header | "Review 9 tasks" — "Edit before they land in your inbox" |
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
- **Semantics:** rose-600 destructive + due dates + recording, emerald-500 success + **agent states**, amber-600 warnings + review-due + **agent "Needs you"**, sky-500 info + **thinking/canvas states**.
- **Node semantics** (canvas, from `nodeColors.json`): leaf (no outgoing) `#EF4444` white text, root (no incoming) `#FACC15` dark text, default white on slate-900. Load-bearing color logic, not decoration.

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
- **Emerald Sparkles chips + squircle agent avatars** = an agent is doing work for you.

---

## Iconography

**[Lucide](https://lucide.dev)** only — stroke-based, 1.5–2px stroke, 24×24 viewbox, rounded caps. Rendered 16px in buttons/rows, 20px next to headings, 28px in circular badges. Color inherits (`currentColor`); rest state slate-500/600, brand slots sky-500.

**Core icons post-pivot:** `Mic` (brain dump), `Square` (stop recording), `Inbox`, `ArrowRight` (next actions), `Clock` (waiting for), `Archive` (someday), `RotateCcw` (weekly review), `Search`, `Sparkles` (AI executor), `Network` (thinking canvas), `Calendar`, `Trash2`, `Plus`, `X`, `ChevronDown`, `ChevronRight`, `ArrowDownUp` (sort). Canvas set carried over: `Sprout`, `Minus`, `Maximize2`, `AlertTriangle`, `CheckCircle2`, `Info`, `LogOut`, `Download`, `Upload`, `Pencil`, `Save`, `History`, `Layers`, `ShieldCheck`, `Tag`.

No custom SVG illustration, no emoji, no icon fonts. If a symbol is missing, pick the closest Lucide match — never mix libraries.

### Logo mark
Lucide `Sprout` doubles as the product logo (top bar) — see `assets/logo.svg` and `assets/logo-lockup.svg`. **Inferred from product use — flag for review.**

---

## Index

### Root
- `README.md` — you are here
- `SKILL.md` — agent skill descriptor (usable by Claude Code)
- `colors_and_type.css` — CSS variables for colors + type primitives + semantic tokens (incl. AI-state aliases)
- `assets/` — logo, wordmark
- `preview/` — design-system cards for each token set and component cluster
- `ui_kits/workspace/` — Brain Buddy canvas-workspace UI kit (React JSX, interactive demo)

### UI kits
- `ui_kits/workspace/` — the **pre-pivot** canvas app: auth, top bar, canvas with `BrainNode`s, inspector, modals, toasts. Still valid for the thinking-canvas surface, which now opens from a task. A tasks-first shell kit is not built yet — use the task-row/GTD preview cards + Pivot Explorations as reference.

### Notes for iterators
- Everything visual derives from production code + the Pivot Explorations; there is no Figma.
- The tasks-first shell (option 1a), brain dump (1c/1d), and review (1e) are **approved directions, not shipped code** — treat details as canonical until production exists.
- `Sprout`-as-logo is pragmatic; a real brand mark may exist.
- Font delivery via Google Fonts import in `colors_and_type.css`.

---

## Syncing this skill

This directory is pulled from the "Brain Buddy Design System" project on claude.ai/design (project id `ade33f3b-852a-4b58-ae75-256156754f68`) via the `DesignSync` tool. To refresh it, re-pull the listed files from that project; to push local edits back, use `DesignSync` with `finalize_plan` / `write_files` against the same project.
