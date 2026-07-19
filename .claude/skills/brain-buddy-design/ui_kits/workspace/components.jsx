/* Components — Brain Buddy workspace kit. Shared global window-exports. */
const { useState, useEffect, useMemo, useRef } = React;

// ---------- Primitives ----------
const Icon = ({ d, size = 16, stroke = "currentColor", sw = 2, children }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke}
       strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
       style={{ flexShrink: 0 }}>
    {d ? <path d={d} /> : children}
  </svg>
);

const I = {
  Sprout: (p) => <Icon size={p.size} stroke={p.stroke || "#0ea5e9"}>
    <path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/>
    <path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/>
    <path d="M14.1 6a7 7 0 0 0-1.1 4c1.9.1 3.3-.2 4.3-.9 1-.6 1.9-1.8 2.7-3.6-2.4-.5-4-.3-5-.1-.4.1-.7.3-.9.6z"/>
  </Icon>,
  Plus: (p) => <Icon {...p} d="M12 5v14M5 12h14"/>,
  Minus: (p) => <Icon {...p} d="M5 12h14"/>,
  ChevDown: (p) => <Icon {...p} d="m6 9 6 6 6-6"/>,
  X: (p) => <Icon {...p} d="M18 6 6 18M6 6l12 12"/>,
  LogOut: (p) => <Icon {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></Icon>,
  Download: (p) => <Icon {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></Icon>,
  Upload: (p) => <Icon {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></Icon>,
  Pencil: (p) => <Icon {...p} d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>,
  Trash: (p) => <Icon {...p}><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></Icon>,
  Max: (p) => <Icon {...p}><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></Icon>,
  Spark: (p) => <Icon {...p} d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>,
  Shield: (p) => <Icon {...p}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></Icon>,
  Tag: (p) => <Icon {...p}><path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1"/></Icon>,
  Layers: (p) => <Icon {...p}><path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></Icon>,
  Check: (p) => <Icon {...p}><path d="M22 11.1V12a10 10 0 1 1-5.93-9.14"/><path d="m22 4-10 10-3-3"/></Icon>,
  Info: (p) => <Icon {...p}><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></Icon>,
  Alert: (p) => <Icon {...p}><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/></Icon>,
  AlertC: (p) => <Icon {...p}><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></Icon>,
  Rotate: (p) => <Icon {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></Icon>,
  History: (p) => <Icon {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></Icon>,
  Save: (p) => <Icon {...p}><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></Icon>
};

const Button = ({ variant = "primary", size = "md", leftIcon, rightIcon, loading, disabled, children, className = "", ...rest }) => {
  const base = "bb-btn";
  const v = `bb-btn-${variant}`;
  const s = `bb-btn-${size}`;
  const iconOnly = !children;
  return (
    <button {...rest} disabled={disabled || loading}
      className={`${base} ${v} ${s} ${iconOnly ? "bb-btn-icon" : ""} ${className}`}>
      {loading ? <span className="bb-spinner"/> : leftIcon}
      {children && <span>{children}</span>}
      {rightIcon && !loading && rightIcon}
    </button>
  );
};

// ---------- Node ----------
const BrainNode = ({ node, selected, onSelect }) => {
  const { up, down } = node.relationCounts;
  let bg = "#fff", fg = "#0f172a";
  if (down === 0 && up > 0) { bg = "#ef4444"; fg = "#fff"; }
  else if (up === 0) { bg = "#facc15"; fg = "#1f2937"; }
  return (
    <div className={`bb-node ${selected ? "is-selected" : ""}`}
         style={{ left: node.x, top: node.y, background: bg, color: fg }}
         onMouseDown={(e) => { e.stopPropagation(); onSelect(node.id); }}>
      <span className="bb-node-bar"/>
      <span className="bb-node-hl"/>
      {selected && <>
        <span className="bb-handle top"/><span className="bb-handle bottom"/>
        <span className="bb-handle left"/><span className="bb-handle right"/>
      </>}
      <div className="bb-node-label">{node.label}</div>
    </div>
  );
};

// ---------- Edges ----------
const Edges = ({ nodes, edges, selectedId }) => {
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));
  const W = 240, H = 132;
  return (
    <svg className="bb-edges" width="100%" height="100%">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/>
        </marker>
        <marker id="arrow-sel" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#0ea5e9"/>
        </marker>
      </defs>
      {edges.map((e, i) => {
        const s = nodeMap[e.source], t = nodeMap[e.target];
        if (!s || !t) return null;
        const sx = s.x + W / 2, sy = s.y + H;
        const tx = t.x + W / 2, ty = t.y;
        const midY = (sy + ty) / 2;
        const sel = selectedId === e.source || selectedId === e.target;
        return (
          <path key={i}
                d={`M ${sx} ${sy} C ${sx} ${midY} ${tx} ${midY} ${tx} ${ty}`}
                stroke={sel ? "#0ea5e9" : "#94a3b8"} strokeWidth={sel ? 2.5 : 2}
                fill="none" markerEnd={sel ? "url(#arrow-sel)" : "url(#arrow)"}
                style={{ filter: sel ? "drop-shadow(0 0 6px rgba(14,165,233,.35))" : "none" }}/>
        );
      })}
    </svg>
  );
};

// ---------- Canvas ----------
const Canvas = ({ nodes, edges, selectedId, onSelect }) => {
  return (
    <div className="bb-canvas-bg">
      <div className="bb-canvas-inner">
        <Edges nodes={nodes} edges={edges} selectedId={selectedId}/>
        {nodes.map(n => (
          <BrainNode key={n.id} node={n} selected={selectedId === n.id} onSelect={onSelect}/>
        ))}
      </div>
    </div>
  );
};

// ---------- Dropdown ----------
const Dropdown = ({ open, onClose, children, align = "left", width = 280 }) => {
  if (!open) return null;
  return <>
    <div className="bb-backdrop-ghost" onClick={onClose}/>
    <div className="bb-menu" style={{ [align]: 0, minWidth: width }}>{children}</div>
  </>;
};
const MenuItem = ({ icon, onClick, children, danger, disabled }) => (
  <button className={`bb-menu-item ${danger ? "danger" : ""}`} onClick={onClick} disabled={disabled}>
    {icon}<span>{children}</span>
  </button>
);

// ---------- TreeMenu (trigger + menu) ----------
const TreeMenu = ({ treeName, trees, activeId, onSwitch, onNew, onRename, onExport, onImport, onDelete }) => {
  const [open, setOpen] = useState(false);
  const others = trees.filter(t => t.id !== activeId);
  return (
    <div className="bb-relative">
      <button className="bb-tree-trigger" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <I.Sprout size={20}/>
        <span className="bb-tree-name">{treeName}</span>
        <I.ChevDown size={16} stroke="#64748b"/>
      </button>
      <Dropdown open={open} onClose={() => setOpen(false)}>
        <div style={{ padding: 4 }}>
          <MenuItem icon={<I.Plus size={16}/>} onClick={() => { setOpen(false); onNew(); }}>New tree</MenuItem>
          <MenuItem icon={<I.Pencil size={16}/>} onClick={() => { setOpen(false); onRename(); }}>Rename tree</MenuItem>
          <MenuItem icon={<I.Download size={16}/>} onClick={() => { setOpen(false); onExport(); }}>Export to file</MenuItem>
          <MenuItem icon={<I.Upload size={16}/>} onClick={() => { setOpen(false); onImport(); }}>Import from file</MenuItem>
          <MenuItem icon={<I.Trash size={16}/>} danger onClick={() => { setOpen(false); onDelete(); }}>Delete tree</MenuItem>
        </div>
        <div className="bb-menu-sep"/>
        <div className="bb-menu-section-label">Switch tree</div>
        <div style={{ padding: 4, maxHeight: 240, overflowY: "auto" }}>
          {others.length === 0
            ? <div className="bb-menu-empty">No other trees yet</div>
            : others.map(t => (
              <MenuItem key={t.id} onClick={() => { setOpen(false); onSwitch(t.id); }}>
                <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                  <span>{t.name}</span>
                  <span className="bb-micro">Updated {t.updated}</span>
                </span>
              </MenuItem>
            ))}
        </div>
      </Dropdown>
    </div>
  );
};

// ---------- Inspector ----------
const Inspector = ({ node, onRename, onDelete, onValidate, validations }) => {
  const [label, setLabel] = useState(node.label);
  const [nodeType, setNodeType] = useState(node.type || "child");
  const [consent, setConsent] = useState(false);
  useEffect(() => { setLabel(node.label); }, [node.id, node.label]);
  const submit = () => { const t = label.trim(); if (t && t !== node.label) onRename(node.id, t); };

  return (
    <div className="bb-inspector">
      <section>
        <div className="bb-label"><I.Tag size={14}/> Node label</div>
        <input className="bb-input" value={label}
               onChange={e => setLabel(e.target.value)} onBlur={submit}
               onKeyDown={e => e.key === "Enter" && (e.preventDefault(), submit())}/>
        <p className="bb-caption" style={{ marginTop: 6 }}>
          Incoming <b>{node.relationCounts.up}</b> · Outgoing <b>{node.relationCounts.down}</b>
        </p>
      </section>
      <div className="bb-grid2">
        <section className="bb-subcard">
          <div className="bb-label"><I.Layers size={14}/> Type</div>
          <select className="bb-input" value={nodeType} onChange={e => setNodeType(e.target.value)}>
            <option value="parent">Parent</option>
            <option value="child">Child</option>
          </select>
        </section>
        <section className="bb-subcard">
          <div className="bb-label"><I.Spark size={14}/> Highlight</div>
          <select className="bb-input" defaultValue="none">
            <option value="none">None</option>
            <option value="cause_candidate">Cause candidate</option>
            <option value="effect_spanning">Effect spanning</option>
          </select>
        </section>
      </div>
      <section className="bb-subcard">
        <div className="bb-label"><I.Shield size={14}/> Validation</div>
        <p className="bb-caption" style={{ marginTop: 2 }}>Run validation against the selected provider and review history.</p>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
          <Button size="sm" leftIcon={<I.Shield size={14}/>} onClick={() => onValidate(node.id)}>Run validation</Button>
          <span className="bb-micro">Uses the mock provider when none configured.</span>
        </div>
        {validations.length > 0 ? (
          <ul className="bb-validations">
            {validations.slice(-3).reverse().map((v, i) => (
              <li key={i}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b>{v.confidence}%</b>
                  <span className="bb-micro">{v.time}</span>
                </div>
                <p className="bb-caption">{v.summary}</p>
              </li>
            ))}
          </ul>
        ) : (
          <div className="bb-empty-dash">No previous validations recorded.</div>
        )}
      </section>
      <section className="bb-ai-card">
        <div className="bb-label" style={{ color: "#047857" }}><I.Spark size={14}/> AI feedback</div>
        <p className="bb-caption" style={{ color: "#065f46", marginTop: 2 }}>
          Request a quick summary and recommendations.
        </p>
        <label className="bb-consent">
          <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
          <span>I consent to send the current tree to the AI provider for analysis.</span>
        </label>
        <Button size="sm" leftIcon={<I.Spark size={14}/>} disabled={!consent}
                className="bb-emerald">Request feedback</Button>
      </section>
      <Button variant="danger" size="sm" leftIcon={<I.Trash size={14}/>}
              onClick={() => onDelete(node.id)} className="bb-full">Delete node</Button>
    </div>
  );
};

const InspectorPlaceholder = ({ message }) => (
  <div className="bb-placeholder">
    <I.Sprout size={24} stroke="#94a3b8"/>
    <p>{message}</p>
  </div>
);

// ---------- Toast ----------
const Toast = ({ toast, onDismiss }) => {
  const icons = { success: <I.Check size={16}/>, info: <I.Info size={16}/>,
                  warning: <I.Alert size={16}/>, error: <I.AlertC size={16}/> };
  return (
    <div className={`bb-toast variant-${toast.variant}`}>
      <div className="bb-toast-icon">{icons[toast.variant]}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="bb-toast-title">{toast.title}</div>
        {toast.description && <div className="bb-toast-desc">{toast.description}</div>}
      </div>
      <button className="bb-toast-close" onClick={() => onDismiss(toast.id)} aria-label="Dismiss"><I.X size={14}/></button>
    </div>
  );
};

// ---------- Modal ----------
const Modal = ({ open, title, children, onClose }) => {
  if (!open) return null;
  return (
    <div className="bb-modal-backdrop" onClick={onClose}>
      <div className="bb-modal" onClick={e => e.stopPropagation()}>
        <div className="bb-modal-title">{title}</div>
        {children}
      </div>
    </div>
  );
};

// ---------- Auth layout ----------
const AuthShell = ({ title, children }) => (
  <div className="bb-auth-shell">
    <div className="bb-auth-card">
      <div className="bb-auth-brand"><I.Sprout size={22}/><span>Brain Buddy</span></div>
      <h1 className="bb-auth-title">{title}</h1>
      {children}
    </div>
  </div>
);

Object.assign(window, {
  I, Icon, Button, BrainNode, Canvas, Edges,
  Dropdown, MenuItem, TreeMenu, Inspector, InspectorPlaceholder,
  Toast, Modal, AuthShell
});
