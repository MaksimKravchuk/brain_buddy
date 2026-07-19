# Brain Buddy Workspace — UI kit

High-fidelity recreation of the Brain Buddy web app. Click-thru prototype covering:

- Auth (login + signup with invite code)
- Top bar with tree menu dropdown
- Canvas with `BrainNode`s, bezier edges, selection + floating zoom controls
- Side inspector panel for the selected node
- Toast notifications
- Confirm dialogs

Open `index.html` to click through. Derived from `brain_buddy/frontend/src/**` — components here are cosmetic recreations, not production code.

`components.jsx` and `app.jsx` are browser-global scripts loaded in that order by `index.html`; this kit has no module barrel and no `index.js` imports. Keep that loading model when copying the standalone prototype. Production React code should use the production app's own module boundaries rather than importing files from this kit.

> **Pivot note:** this kit covers the **thinking canvas** surface only, which post-pivot opens from a task/project rather than being the app root. The tasks-first shell (GTD sidebar, task list, and brain dump) is documented in the root README + `preview/` cards; no interactive kit for it exists yet. Future Execution cards are speculative and non-shipped.
