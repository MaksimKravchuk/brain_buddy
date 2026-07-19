# Brain Buddy Workspace — UI kit

High-fidelity recreation of the Brain Buddy web app. Click-thru prototype covering:

- Auth (login + signup with invite code)
- Top bar with tree menu dropdown
- Canvas with `BrainNode`s, bezier edges, selection + floating zoom controls
- Side inspector panel for the selected node
- Toast notifications
- Confirm dialogs

Open `index.html` to click through. Derived from `brain_buddy/frontend/src/**` — components here are cosmetic recreations, not production code.

> **Pivot note:** this kit covers the **thinking canvas** surface only, which post-pivot opens from a task/project rather than being the app root. The tasks-first shell (GTD sidebar, task list, brain dump, AI executor states) is documented in the root README + `preview/` cards; no interactive kit for it exists yet.
