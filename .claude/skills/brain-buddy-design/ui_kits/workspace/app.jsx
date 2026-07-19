/* Brain Buddy workspace app — click-thru prototype. */
const { useState, useRef } = React;

const DEMO_TREES = [
  { id: "t1", name: "Supply chain CRT", updated: "4m ago" },
  { id: "t2", name: "Onboarding friction", updated: "2h ago" },
  { id: "t3", name: "Pricing assumptions", updated: "1d ago" }
];

const INITIAL_NODES = [
  { id: "n1", label: "Customers churn within 30 days", x: 440, y: 460, relationCounts: { up: 2, down: 0 } },
  { id: "n2", label: "Onboarding feels abstract", x: 200, y: 280, relationCounts: { up: 1, down: 1 } },
  { id: "n3", label: "First value takes > 10 minutes", x: 680, y: 280, relationCounts: { up: 1, down: 1 } },
  { id: "n4", label: "Sample data not installed on signup", x: 440, y: 80, relationCounts: { up: 0, down: 2 } }
];
const INITIAL_EDGES = [
  { source: "n4", target: "n2" },
  { source: "n4", target: "n3" },
  { source: "n2", target: "n1" },
  { source: "n3", target: "n1" }
];

let toastId = 0;

function App() {
  // Auth
  const [view, setView] = useState("login"); // login | signup | workspace
  const [email, setEmail] = useState("taylor@example.com");
  const [password, setPassword] = useState("averysecretpw12");
  const [invite, setInvite] = useState("");
  const [authErr, setAuthErr] = useState(null);

  // Workspace
  const [trees, setTrees] = useState(DEMO_TREES);
  const [activeId, setActiveId] = useState("t1");
  const activeTree = trees.find(t => t.id === activeId) || trees[0];
  const [nodes, setNodes] = useState(INITIAL_NODES);
  const [edges] = useState(INITIAL_EDGES);
  const [selectedId, setSelectedId] = useState("n2");
  const [validations, setValidations] = useState([]);

  // Modals
  const [modal, setModal] = useState(null); // "new" | "rename" | "delete" | null
  const [newName, setNewName] = useState("");

  // Toasts
  const [toasts, setToasts] = useState([]);
  const pushToast = (t) => {
    const id = ++toastId;
    setToasts(s => [...s, { id, ...t }]);
    if ((t.duration ?? 3500) > 0) {
      setTimeout(() => setToasts(s => s.filter(x => x.id !== id)), t.duration ?? 3500);
    }
    return id;
  };
  const dismissToast = (id) => setToasts(s => s.filter(x => x.id !== id));

  const selectedNode = nodes.find(n => n.id === selectedId);

  // ---- auth actions ----
  const doLogin = (e) => {
    e.preventDefault();
    setAuthErr(null);
    if (!email.includes("@")) return setAuthErr("Enter a valid email.");
    if (password.length < 12) return setAuthErr("Password must be at least 12 characters.");
    setView("workspace");
    pushToast({ title: "Welcome back", description: email, variant: "success" });
  };
  const doSignup = (e) => {
    e.preventDefault();
    setAuthErr(null);
    if (password.length < 12) return setAuthErr("Password must be at least 12 characters.");
    if (!invite.trim()) return setAuthErr("Invite code is invalid or already used.");
    setView("workspace");
    pushToast({ title: "Account created", description: "Your first tree is ready.", variant: "success" });
  };
  const doLogout = () => {
    setView("login");
    pushToast({ title: "Signed out", variant: "info" });
  };

  // ---- tree/node actions ----
  const onRenameNode = (id, label) => {
    setNodes(ns => ns.map(n => n.id === id ? { ...n, label } : n));
    pushToast({ title: "Node updated", description: "Label saved.", variant: "success", duration: 2500 });
  };
  const onDeleteNode = (id) => {
    setNodes(ns => ns.filter(n => n.id !== id));
    setSelectedId(null);
    pushToast({ title: "Node removed", description: "Node deleted from the tree.", variant: "info" });
  };
  const onValidate = (id) => {
    const confidence = 55 + Math.floor(Math.random() * 40);
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setValidations(v => [...v, { confidence, time, summary: "Reasoning chain is coherent; check assumption on onboarding timing." }]);
    pushToast({ title: "Validation updated", description: `Confidence ${confidence}%`, variant: "success" });
  };
  const onNewTree = () => { setNewName(""); setModal("new"); };
  const createTree = () => {
    const n = newName.trim() || "Untitled tree";
    const id = "t" + (trees.length + 1);
    setTrees(ts => [{ id, name: n, updated: "just now" }, ...ts]);
    setActiveId(id);
    setModal(null);
    pushToast({ title: "Tree created", description: n, variant: "success" });
  };
  const deleteTree = () => {
    const remaining = trees.filter(t => t.id !== activeId);
    setTrees(remaining);
    setActiveId(remaining[0]?.id);
    setModal(null);
    pushToast({ title: "Tree deleted", variant: "info" });
  };
  const renameTree = () => {
    const n = newName.trim();
    if (!n) return;
    setTrees(ts => ts.map(t => t.id === activeId ? { ...t, name: n, updated: "just now" } : t));
    setModal(null);
    pushToast({ title: "Tree renamed", description: n, variant: "success" });
  };

  // ---- renders ----
  if (view === "login") {
    return (
      <>
        <AuthShell title="Sign in to Brain Buddy">
          <form onSubmit={doLogin}>
            <div className="bb-field">
              <label className="bb-field-label">Email</label>
              <input className="bb-input" type="email" value={email} onChange={e => setEmail(e.target.value)}/>
            </div>
            <div className="bb-field">
              <label className="bb-field-label">Password</label>
              <input className="bb-input" type="password" value={password} onChange={e => setPassword(e.target.value)}/>
            </div>
            {authErr && <p className="bb-field-err">{authErr}</p>}
            <Button type="submit" className="bb-full">Sign in</Button>
            <p className="bb-auth-footer">
              Have an invite code?{" "}
              <a onClick={() => { setAuthErr(null); setView("signup"); }}>Create an account</a>
            </p>
          </form>
        </AuthShell>
        <ToastStack toasts={toasts} onDismiss={dismissToast}/>
      </>
    );
  }
  if (view === "signup") {
    return (
      <>
        <AuthShell title="Create your account">
          <form onSubmit={doSignup}>
            <div className="bb-field">
              <label className="bb-field-label">Email</label>
              <input className="bb-input" type="email" value={email} onChange={e => setEmail(e.target.value)}/>
            </div>
            <div className="bb-field">
              <label className="bb-field-label">Password</label>
              <input className="bb-input" type="password" value={password} onChange={e => setPassword(e.target.value)}/>
              <span className="bb-field-hint">At least 12 characters. Longer is better.</span>
            </div>
            <div className="bb-field">
              <label className="bb-field-label">Invite code</label>
              <input className="bb-input" value={invite} onChange={e => setInvite(e.target.value)}
                     style={{ fontFamily: "ui-monospace, Menlo, monospace" }} placeholder="BB-XXXX-XXXX"/>
            </div>
            {authErr && <p className="bb-field-err">{authErr}</p>}
            <Button type="submit" className="bb-full">Create account</Button>
            <p className="bb-auth-footer">
              Already have an account?{" "}
              <a onClick={() => { setAuthErr(null); setView("login"); }}>Sign in</a>
            </p>
          </form>
        </AuthShell>
        <ToastStack toasts={toasts} onDismiss={dismissToast}/>
      </>
    );
  }

  // Workspace
  return (
    <div className="bb-app">
      <header className="bb-header">
        <TreeMenu
          treeName={activeTree?.name || "Untitled tree"}
          trees={trees} activeId={activeId}
          onSwitch={setActiveId}
          onNew={onNewTree}
          onRename={() => { setNewName(activeTree.name); setModal("rename"); }}
          onExport={() => pushToast({ title: "Export ready", description: `${activeTree.name}.json`, variant: "success" })}
          onImport={() => pushToast({ title: "Importing…", description: "Validating JSON structure", variant: "info" })}
          onDelete={() => setModal("delete")}
        />
        <div className="bb-header-right">
          <span title={email}>{email}</span>
          <Button variant="secondary" size="sm" leftIcon={<I.LogOut size={14}/>} onClick={doLogout}>Sign out</Button>
        </div>
      </header>
      <div className="bb-main">
        <main className="bb-stage">
          {activeTree ? (
            <Canvas nodes={nodes} edges={edges} selectedId={selectedId} onSelect={setSelectedId}/>
          ) : (
            <div className="bb-empty-canvas">
              <div className="in">
                <div className="badge"><I.Sprout size={28}/></div>
                <h2>Start with your first undesired effect</h2>
                <p>Create a new tree to drop in your initial thought and build from there.</p>
                <Button leftIcon={<I.Plus size={16}/>} onClick={onNewTree}>Create a new tree</Button>
              </div>
            </div>
          )}
          {activeTree && (
            <div className="bb-zoom">
              <Button variant="ghost" size="sm" leftIcon={<I.Plus size={16}/>}/>
              <Button variant="ghost" size="sm" leftIcon={<I.Minus size={16}/>}/>
              <div className="sep"/>
              <Button variant="ghost" size="sm" leftIcon={<I.Max size={16}/>}/>
            </div>
          )}
        </main>
        <aside className="bb-side">
          <div className="bb-side-pad">
            {selectedNode ? (
              <Inspector node={selectedNode}
                onRename={onRenameNode}
                onDelete={onDeleteNode}
                onValidate={onValidate}
                validations={validations}/>
            ) : (
              <InspectorPlaceholder message="Select a node on the canvas to view its details."/>
            )}
          </div>
        </aside>
      </div>

      {/* Modals */}
      <Modal open={modal === "new"} onClose={() => setModal(null)} title="Create a new tree">
        <div className="bb-field">
          <label className="bb-field-label">Tree name</label>
          <input className="bb-input" placeholder="e.g. Churn root causes" value={newName} onChange={e => setNewName(e.target.value)} autoFocus/>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
          <Button onClick={createTree}>Create tree</Button>
        </div>
      </Modal>
      <Modal open={modal === "rename"} onClose={() => setModal(null)} title="Rename tree">
        <div className="bb-field">
          <label className="bb-field-label">Name</label>
          <input className="bb-input" value={newName} onChange={e => setNewName(e.target.value)} autoFocus/>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
          <Button onClick={renameTree}>Save</Button>
        </div>
      </Modal>
      <Modal open={modal === "delete"} onClose={() => setModal(null)} title="Delete this tree?">
        <p className="bb-caption">Delete "{activeTree?.name}"? This permanently removes the tree and all of its snapshots.</p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
          <Button variant="danger" leftIcon={<I.Trash size={14}/>} onClick={deleteTree}>Delete tree</Button>
        </div>
      </Modal>

      <ToastStack toasts={toasts} onDismiss={dismissToast}/>
    </div>
  );
}

function ToastStack({ toasts, onDismiss }) {
  return <div className="bb-toast-stack">{toasts.map(t => <Toast key={t.id} toast={t} onDismiss={onDismiss}/>)}</div>;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
