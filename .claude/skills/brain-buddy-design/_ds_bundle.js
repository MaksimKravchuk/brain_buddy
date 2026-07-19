/* @ds-bundle: {"format":4,"namespace":"BrainBuddyDesignSystem_ade33f","components":[],"sourceHashes":{"ui_kits/workspace/app.jsx":"529a44345659","ui_kits/workspace/components.jsx":"07a5eca26e34"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.BrainBuddyDesignSystem_ade33f = window.BrainBuddyDesignSystem_ade33f || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// ui_kits/workspace/app.jsx
try { (() => {
/* Brain Buddy workspace app — click-thru prototype. */
const {
  useState,
  useRef
} = React;
const DEMO_TREES = [{
  id: "t1",
  name: "Supply chain CRT",
  updated: "4m ago"
}, {
  id: "t2",
  name: "Onboarding friction",
  updated: "2h ago"
}, {
  id: "t3",
  name: "Pricing assumptions",
  updated: "1d ago"
}];
const INITIAL_NODES = [{
  id: "n1",
  label: "Customers churn within 30 days",
  x: 440,
  y: 460,
  relationCounts: {
    up: 2,
    down: 0
  }
}, {
  id: "n2",
  label: "Onboarding feels abstract",
  x: 200,
  y: 280,
  relationCounts: {
    up: 1,
    down: 1
  }
}, {
  id: "n3",
  label: "First value takes > 10 minutes",
  x: 680,
  y: 280,
  relationCounts: {
    up: 1,
    down: 1
  }
}, {
  id: "n4",
  label: "Sample data not installed on signup",
  x: 440,
  y: 80,
  relationCounts: {
    up: 0,
    down: 2
  }
}];
const INITIAL_EDGES = [{
  source: "n4",
  target: "n2"
}, {
  source: "n4",
  target: "n3"
}, {
  source: "n2",
  target: "n1"
}, {
  source: "n3",
  target: "n1"
}];
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
  const pushToast = t => {
    const id = ++toastId;
    setToasts(s => [...s, {
      id,
      ...t
    }]);
    if ((t.duration ?? 3500) > 0) {
      setTimeout(() => setToasts(s => s.filter(x => x.id !== id)), t.duration ?? 3500);
    }
    return id;
  };
  const dismissToast = id => setToasts(s => s.filter(x => x.id !== id));
  const selectedNode = nodes.find(n => n.id === selectedId);

  // ---- auth actions ----
  const doLogin = e => {
    e.preventDefault();
    setAuthErr(null);
    if (!email.includes("@")) return setAuthErr("Enter a valid email.");
    if (password.length < 12) return setAuthErr("Password must be at least 12 characters.");
    setView("workspace");
    pushToast({
      title: "Welcome back",
      description: email,
      variant: "success"
    });
  };
  const doSignup = e => {
    e.preventDefault();
    setAuthErr(null);
    if (password.length < 12) return setAuthErr("Password must be at least 12 characters.");
    if (!invite.trim()) return setAuthErr("Invite code is invalid or already used.");
    setView("workspace");
    pushToast({
      title: "Account created",
      description: "Your first tree is ready.",
      variant: "success"
    });
  };
  const doLogout = () => {
    setView("login");
    pushToast({
      title: "Signed out",
      variant: "info"
    });
  };

  // ---- tree/node actions ----
  const onRenameNode = (id, label) => {
    setNodes(ns => ns.map(n => n.id === id ? {
      ...n,
      label
    } : n));
    pushToast({
      title: "Node updated",
      description: "Label saved.",
      variant: "success",
      duration: 2500
    });
  };
  const onDeleteNode = id => {
    setNodes(ns => ns.filter(n => n.id !== id));
    setSelectedId(null);
    pushToast({
      title: "Node removed",
      description: "Node deleted from the tree.",
      variant: "info"
    });
  };
  const onValidate = id => {
    const confidence = 55 + Math.floor(Math.random() * 40);
    const time = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
    setValidations(v => [...v, {
      confidence,
      time,
      summary: "Reasoning chain is coherent; check assumption on onboarding timing."
    }]);
    pushToast({
      title: "Validation updated",
      description: `Confidence ${confidence}%`,
      variant: "success"
    });
  };
  const onNewTree = () => {
    setNewName("");
    setModal("new");
  };
  const createTree = () => {
    const n = newName.trim() || "Untitled tree";
    const id = "t" + (trees.length + 1);
    setTrees(ts => [{
      id,
      name: n,
      updated: "just now"
    }, ...ts]);
    setActiveId(id);
    setModal(null);
    pushToast({
      title: "Tree created",
      description: n,
      variant: "success"
    });
  };
  const deleteTree = () => {
    const remaining = trees.filter(t => t.id !== activeId);
    setTrees(remaining);
    setActiveId(remaining[0]?.id);
    setModal(null);
    pushToast({
      title: "Tree deleted",
      variant: "info"
    });
  };
  const renameTree = () => {
    const n = newName.trim();
    if (!n) return;
    setTrees(ts => ts.map(t => t.id === activeId ? {
      ...t,
      name: n,
      updated: "just now"
    } : t));
    setModal(null);
    pushToast({
      title: "Tree renamed",
      description: n,
      variant: "success"
    });
  };

  // ---- renders ----
  if (view === "login") {
    return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(AuthShell, {
      title: "Sign in to Brain Buddy"
    }, /*#__PURE__*/React.createElement("form", {
      onSubmit: doLogin
    }, /*#__PURE__*/React.createElement("div", {
      className: "bb-field"
    }, /*#__PURE__*/React.createElement("label", {
      className: "bb-field-label"
    }, "Email"), /*#__PURE__*/React.createElement("input", {
      className: "bb-input",
      type: "email",
      value: email,
      onChange: e => setEmail(e.target.value)
    })), /*#__PURE__*/React.createElement("div", {
      className: "bb-field"
    }, /*#__PURE__*/React.createElement("label", {
      className: "bb-field-label"
    }, "Password"), /*#__PURE__*/React.createElement("input", {
      className: "bb-input",
      type: "password",
      value: password,
      onChange: e => setPassword(e.target.value)
    })), authErr && /*#__PURE__*/React.createElement("p", {
      className: "bb-field-err"
    }, authErr), /*#__PURE__*/React.createElement(Button, {
      type: "submit",
      className: "bb-full"
    }, "Sign in"), /*#__PURE__*/React.createElement("p", {
      className: "bb-auth-footer"
    }, "Have an invite code?", " ", /*#__PURE__*/React.createElement("a", {
      onClick: () => {
        setAuthErr(null);
        setView("signup");
      }
    }, "Create an account")))), /*#__PURE__*/React.createElement(ToastStack, {
      toasts: toasts,
      onDismiss: dismissToast
    }));
  }
  if (view === "signup") {
    return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(AuthShell, {
      title: "Create your account"
    }, /*#__PURE__*/React.createElement("form", {
      onSubmit: doSignup
    }, /*#__PURE__*/React.createElement("div", {
      className: "bb-field"
    }, /*#__PURE__*/React.createElement("label", {
      className: "bb-field-label"
    }, "Email"), /*#__PURE__*/React.createElement("input", {
      className: "bb-input",
      type: "email",
      value: email,
      onChange: e => setEmail(e.target.value)
    })), /*#__PURE__*/React.createElement("div", {
      className: "bb-field"
    }, /*#__PURE__*/React.createElement("label", {
      className: "bb-field-label"
    }, "Password"), /*#__PURE__*/React.createElement("input", {
      className: "bb-input",
      type: "password",
      value: password,
      onChange: e => setPassword(e.target.value)
    }), /*#__PURE__*/React.createElement("span", {
      className: "bb-field-hint"
    }, "At least 12 characters. Longer is better.")), /*#__PURE__*/React.createElement("div", {
      className: "bb-field"
    }, /*#__PURE__*/React.createElement("label", {
      className: "bb-field-label"
    }, "Invite code"), /*#__PURE__*/React.createElement("input", {
      className: "bb-input",
      value: invite,
      onChange: e => setInvite(e.target.value),
      style: {
        fontFamily: "ui-monospace, Menlo, monospace"
      },
      placeholder: "BB-XXXX-XXXX"
    })), authErr && /*#__PURE__*/React.createElement("p", {
      className: "bb-field-err"
    }, authErr), /*#__PURE__*/React.createElement(Button, {
      type: "submit",
      className: "bb-full"
    }, "Create account"), /*#__PURE__*/React.createElement("p", {
      className: "bb-auth-footer"
    }, "Already have an account?", " ", /*#__PURE__*/React.createElement("a", {
      onClick: () => {
        setAuthErr(null);
        setView("login");
      }
    }, "Sign in")))), /*#__PURE__*/React.createElement(ToastStack, {
      toasts: toasts,
      onDismiss: dismissToast
    }));
  }

  // Workspace
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-app"
  }, /*#__PURE__*/React.createElement("header", {
    className: "bb-header"
  }, /*#__PURE__*/React.createElement(TreeMenu, {
    treeName: activeTree?.name || "Untitled tree",
    trees: trees,
    activeId: activeId,
    onSwitch: setActiveId,
    onNew: onNewTree,
    onRename: () => {
      setNewName(activeTree.name);
      setModal("rename");
    },
    onExport: () => pushToast({
      title: "Export ready",
      description: `${activeTree.name}.json`,
      variant: "success"
    }),
    onImport: () => pushToast({
      title: "Importing…",
      description: "Validating JSON structure",
      variant: "info"
    }),
    onDelete: () => setModal("delete")
  }), /*#__PURE__*/React.createElement("div", {
    className: "bb-header-right"
  }, /*#__PURE__*/React.createElement("span", {
    title: email
  }, email), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.LogOut, {
      size: 14
    }),
    onClick: doLogout
  }, "Sign out"))), /*#__PURE__*/React.createElement("div", {
    className: "bb-main"
  }, /*#__PURE__*/React.createElement("main", {
    className: "bb-stage"
  }, activeTree ? /*#__PURE__*/React.createElement(Canvas, {
    nodes: nodes,
    edges: edges,
    selectedId: selectedId,
    onSelect: setSelectedId
  }) : /*#__PURE__*/React.createElement("div", {
    className: "bb-empty-canvas"
  }, /*#__PURE__*/React.createElement("div", {
    className: "in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "badge"
  }, /*#__PURE__*/React.createElement(I.Sprout, {
    size: 28
  })), /*#__PURE__*/React.createElement("h2", null, "Start with your first undesired effect"), /*#__PURE__*/React.createElement("p", null, "Create a new tree to drop in your initial thought and build from there."), /*#__PURE__*/React.createElement(Button, {
    leftIcon: /*#__PURE__*/React.createElement(I.Plus, {
      size: 16
    }),
    onClick: onNewTree
  }, "Create a new tree"))), activeTree && /*#__PURE__*/React.createElement("div", {
    className: "bb-zoom"
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Plus, {
      size: 16
    })
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Minus, {
      size: 16
    })
  }), /*#__PURE__*/React.createElement("div", {
    className: "sep"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Max, {
      size: 16
    })
  }))), /*#__PURE__*/React.createElement("aside", {
    className: "bb-side"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-side-pad"
  }, selectedNode ? /*#__PURE__*/React.createElement(Inspector, {
    node: selectedNode,
    onRename: onRenameNode,
    onDelete: onDeleteNode,
    onValidate: onValidate,
    validations: validations
  }) : /*#__PURE__*/React.createElement(InspectorPlaceholder, {
    message: "Select a node on the canvas to view its details."
  })))), /*#__PURE__*/React.createElement(Modal, {
    open: modal === "new",
    onClose: () => setModal(null),
    title: "Create a new tree"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-field"
  }, /*#__PURE__*/React.createElement("label", {
    className: "bb-field-label"
  }, "Tree name"), /*#__PURE__*/React.createElement("input", {
    className: "bb-input",
    placeholder: "e.g. Churn root causes",
    value: newName,
    onChange: e => setNewName(e.target.value),
    autoFocus: true
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: 8,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    onClick: () => setModal(null)
  }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
    onClick: createTree
  }, "Create tree"))), /*#__PURE__*/React.createElement(Modal, {
    open: modal === "rename",
    onClose: () => setModal(null),
    title: "Rename tree"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-field"
  }, /*#__PURE__*/React.createElement("label", {
    className: "bb-field-label"
  }, "Name"), /*#__PURE__*/React.createElement("input", {
    className: "bb-input",
    value: newName,
    onChange: e => setNewName(e.target.value),
    autoFocus: true
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: 8,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    onClick: () => setModal(null)
  }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
    onClick: renameTree
  }, "Save"))), /*#__PURE__*/React.createElement(Modal, {
    open: modal === "delete",
    onClose: () => setModal(null),
    title: "Delete this tree?"
  }, /*#__PURE__*/React.createElement("p", {
    className: "bb-caption"
  }, "Delete \"", activeTree?.name, "\"? This permanently removes the tree and all of its snapshots."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: 8,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    onClick: () => setModal(null)
  }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
    variant: "danger",
    leftIcon: /*#__PURE__*/React.createElement(I.Trash, {
      size: 14
    }),
    onClick: deleteTree
  }, "Delete tree"))), /*#__PURE__*/React.createElement(ToastStack, {
    toasts: toasts,
    onDismiss: dismissToast
  }));
}
function ToastStack({
  toasts,
  onDismiss
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-toast-stack"
  }, toasts.map(t => /*#__PURE__*/React.createElement(Toast, {
    key: t.id,
    toast: t,
    onDismiss: onDismiss
  })));
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/workspace/app.jsx", error: String((e && e.message) || e) }); }

// ui_kits/workspace/components.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Components — Brain Buddy workspace kit. Shared global window-exports. */
const {
  useState,
  useEffect,
  useMemo,
  useRef
} = React;

// ---------- Primitives ----------
const Icon = ({
  d,
  size = 16,
  stroke = "currentColor",
  sw = 2,
  children
}) => /*#__PURE__*/React.createElement("svg", {
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: stroke,
  strokeWidth: sw,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  style: {
    flexShrink: 0
  }
}, d ? /*#__PURE__*/React.createElement("path", {
  d: d
}) : children);
const I = {
  Sprout: p => /*#__PURE__*/React.createElement(Icon, {
    size: p.size,
    stroke: p.stroke || "#0ea5e9"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M7 20h10"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M10 20c5.5-2.5.8-6.4 3-10"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M14.1 6a7 7 0 0 0-1.1 4c1.9.1 3.3-.2 4.3-.9 1-.6 1.9-1.8 2.7-3.6-2.4-.5-4-.3-5-.1-.4.1-.7.3-.9.6z"
  })),
  Plus: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "M12 5v14M5 12h14"
  })),
  Minus: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "M5 12h14"
  })),
  ChevDown: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "m6 9 6 6 6-6"
  })),
  X: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "M18 6 6 18M6 6l12 12"
  })),
  LogOut: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M16 17l5-5-5-5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M21 12H9"
  })),
  Download: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M7 10l5 5 5-5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 15V3"
  })),
  Upload: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 8l-5-5-5 5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 3v12"
  })),
  Pencil: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"
  })),
  Trash: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M3 6h18"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"
  })),
  Max: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M8 3H5a2 2 0 0 0-2 2v3"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M21 8V5a2 2 0 0 0-2-2h-3"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M3 16v3a2 2 0 0 0 2 2h3"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M16 21h3a2 2 0 0 0 2-2v-3"
  })),
  Spark: p => /*#__PURE__*/React.createElement(Icon, _extends({}, p, {
    d: "m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"
  })),
  Shield: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m9 12 2 2 4-4"
  })),
  Tag: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "7",
    cy: "7",
    r: "1"
  })),
  Layers: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "m12 2 10 5-10 5L2 7z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m2 17 10 5 10-5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m2 12 10 5 10-5"
  })),
  Check: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M22 11.1V12a10 10 0 1 1-5.93-9.14"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m22 4-10 10-3-3"
  })),
  Info: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "10"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 16v-4M12 8h.01"
  })),
  Alert: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 9v4M12 17h.01"
  })),
  AlertC: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "10"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 8v4M12 16h.01"
  })),
  Rotate: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M3 12a9 9 0 1 0 3-6.7L3 8"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M3 3v5h5"
  })),
  History: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M3 12a9 9 0 1 0 3-6.7L3 8"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M3 3v5h5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 7v5l4 2"
  })),
  Save: p => /*#__PURE__*/React.createElement(Icon, p, /*#__PURE__*/React.createElement("path", {
    d: "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 21v-8H7v8"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M7 3v5h8"
  }))
};
const Button = ({
  variant = "primary",
  size = "md",
  leftIcon,
  rightIcon,
  loading,
  disabled,
  children,
  className = "",
  ...rest
}) => {
  const base = "bb-btn";
  const v = `bb-btn-${variant}`;
  const s = `bb-btn-${size}`;
  const iconOnly = !children;
  return /*#__PURE__*/React.createElement("button", _extends({}, rest, {
    disabled: disabled || loading,
    className: `${base} ${v} ${s} ${iconOnly ? "bb-btn-icon" : ""} ${className}`
  }), loading ? /*#__PURE__*/React.createElement("span", {
    className: "bb-spinner"
  }) : leftIcon, children && /*#__PURE__*/React.createElement("span", null, children), rightIcon && !loading && rightIcon);
};

// ---------- Node ----------
const BrainNode = ({
  node,
  selected,
  onSelect
}) => {
  const {
    up,
    down
  } = node.relationCounts;
  let bg = "#fff",
    fg = "#0f172a";
  if (down === 0 && up > 0) {
    bg = "#ef4444";
    fg = "#fff";
  } else if (up === 0) {
    bg = "#facc15";
    fg = "#1f2937";
  }
  return /*#__PURE__*/React.createElement("div", {
    className: `bb-node ${selected ? "is-selected" : ""}`,
    style: {
      left: node.x,
      top: node.y,
      background: bg,
      color: fg
    },
    onMouseDown: e => {
      e.stopPropagation();
      onSelect(node.id);
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "bb-node-bar"
  }), /*#__PURE__*/React.createElement("span", {
    className: "bb-node-hl"
  }), selected && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    className: "bb-handle top"
  }), /*#__PURE__*/React.createElement("span", {
    className: "bb-handle bottom"
  }), /*#__PURE__*/React.createElement("span", {
    className: "bb-handle left"
  }), /*#__PURE__*/React.createElement("span", {
    className: "bb-handle right"
  })), /*#__PURE__*/React.createElement("div", {
    className: "bb-node-label"
  }, node.label));
};

// ---------- Edges ----------
const Edges = ({
  nodes,
  edges,
  selectedId
}) => {
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));
  const W = 240,
    H = 132;
  return /*#__PURE__*/React.createElement("svg", {
    className: "bb-edges",
    width: "100%",
    height: "100%"
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("marker", {
    id: "arrow",
    viewBox: "0 0 10 10",
    refX: "8",
    refY: "5",
    markerWidth: "6",
    markerHeight: "6",
    orient: "auto"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M0,0 L10,5 L0,10 z",
    fill: "#94a3b8"
  })), /*#__PURE__*/React.createElement("marker", {
    id: "arrow-sel",
    viewBox: "0 0 10 10",
    refX: "8",
    refY: "5",
    markerWidth: "6",
    markerHeight: "6",
    orient: "auto"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M0,0 L10,5 L0,10 z",
    fill: "#0ea5e9"
  }))), edges.map((e, i) => {
    const s = nodeMap[e.source],
      t = nodeMap[e.target];
    if (!s || !t) return null;
    const sx = s.x + W / 2,
      sy = s.y + H;
    const tx = t.x + W / 2,
      ty = t.y;
    const midY = (sy + ty) / 2;
    const sel = selectedId === e.source || selectedId === e.target;
    return /*#__PURE__*/React.createElement("path", {
      key: i,
      d: `M ${sx} ${sy} C ${sx} ${midY} ${tx} ${midY} ${tx} ${ty}`,
      stroke: sel ? "#0ea5e9" : "#94a3b8",
      strokeWidth: sel ? 2.5 : 2,
      fill: "none",
      markerEnd: sel ? "url(#arrow-sel)" : "url(#arrow)",
      style: {
        filter: sel ? "drop-shadow(0 0 6px rgba(14,165,233,.35))" : "none"
      }
    });
  }));
};

// ---------- Canvas ----------
const Canvas = ({
  nodes,
  edges,
  selectedId,
  onSelect
}) => {
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-canvas-bg"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-canvas-inner"
  }, /*#__PURE__*/React.createElement(Edges, {
    nodes: nodes,
    edges: edges,
    selectedId: selectedId
  }), nodes.map(n => /*#__PURE__*/React.createElement(BrainNode, {
    key: n.id,
    node: n,
    selected: selectedId === n.id,
    onSelect: onSelect
  }))));
};

// ---------- Dropdown ----------
const Dropdown = ({
  open,
  onClose,
  children,
  align = "left",
  width = 280
}) => {
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "bb-backdrop-ghost",
    onClick: onClose
  }), /*#__PURE__*/React.createElement("div", {
    className: "bb-menu",
    style: {
      [align]: 0,
      minWidth: width
    }
  }, children));
};
const MenuItem = ({
  icon,
  onClick,
  children,
  danger,
  disabled
}) => /*#__PURE__*/React.createElement("button", {
  className: `bb-menu-item ${danger ? "danger" : ""}`,
  onClick: onClick,
  disabled: disabled
}, icon, /*#__PURE__*/React.createElement("span", null, children));

// ---------- TreeMenu (trigger + menu) ----------
const TreeMenu = ({
  treeName,
  trees,
  activeId,
  onSwitch,
  onNew,
  onRename,
  onExport,
  onImport,
  onDelete
}) => {
  const [open, setOpen] = useState(false);
  const others = trees.filter(t => t.id !== activeId);
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-relative"
  }, /*#__PURE__*/React.createElement("button", {
    className: "bb-tree-trigger",
    onClick: () => setOpen(o => !o),
    "aria-expanded": open
  }, /*#__PURE__*/React.createElement(I.Sprout, {
    size: 20
  }), /*#__PURE__*/React.createElement("span", {
    className: "bb-tree-name"
  }, treeName), /*#__PURE__*/React.createElement(I.ChevDown, {
    size: 16,
    stroke: "#64748b"
  })), /*#__PURE__*/React.createElement(Dropdown, {
    open: open,
    onClose: () => setOpen(false)
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 4
    }
  }, /*#__PURE__*/React.createElement(MenuItem, {
    icon: /*#__PURE__*/React.createElement(I.Plus, {
      size: 16
    }),
    onClick: () => {
      setOpen(false);
      onNew();
    }
  }, "New tree"), /*#__PURE__*/React.createElement(MenuItem, {
    icon: /*#__PURE__*/React.createElement(I.Pencil, {
      size: 16
    }),
    onClick: () => {
      setOpen(false);
      onRename();
    }
  }, "Rename tree"), /*#__PURE__*/React.createElement(MenuItem, {
    icon: /*#__PURE__*/React.createElement(I.Download, {
      size: 16
    }),
    onClick: () => {
      setOpen(false);
      onExport();
    }
  }, "Export to file"), /*#__PURE__*/React.createElement(MenuItem, {
    icon: /*#__PURE__*/React.createElement(I.Upload, {
      size: 16
    }),
    onClick: () => {
      setOpen(false);
      onImport();
    }
  }, "Import from file"), /*#__PURE__*/React.createElement(MenuItem, {
    icon: /*#__PURE__*/React.createElement(I.Trash, {
      size: 16
    }),
    danger: true,
    onClick: () => {
      setOpen(false);
      onDelete();
    }
  }, "Delete tree")), /*#__PURE__*/React.createElement("div", {
    className: "bb-menu-sep"
  }), /*#__PURE__*/React.createElement("div", {
    className: "bb-menu-section-label"
  }, "Switch tree"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 4,
      maxHeight: 240,
      overflowY: "auto"
    }
  }, others.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "bb-menu-empty"
  }, "No other trees yet") : others.map(t => /*#__PURE__*/React.createElement(MenuItem, {
    key: t.id,
    onClick: () => {
      setOpen(false);
      onSwitch(t.id);
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "flex-start"
    }
  }, /*#__PURE__*/React.createElement("span", null, t.name), /*#__PURE__*/React.createElement("span", {
    className: "bb-micro"
  }, "Updated ", t.updated)))))));
};

// ---------- Inspector ----------
const Inspector = ({
  node,
  onRename,
  onDelete,
  onValidate,
  validations
}) => {
  const [label, setLabel] = useState(node.label);
  const [nodeType, setNodeType] = useState(node.type || "child");
  const [consent, setConsent] = useState(false);
  useEffect(() => {
    setLabel(node.label);
  }, [node.id, node.label]);
  const submit = () => {
    const t = label.trim();
    if (t && t !== node.label) onRename(node.id, t);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-inspector"
  }, /*#__PURE__*/React.createElement("section", null, /*#__PURE__*/React.createElement("div", {
    className: "bb-label"
  }, /*#__PURE__*/React.createElement(I.Tag, {
    size: 14
  }), " Node label"), /*#__PURE__*/React.createElement("input", {
    className: "bb-input",
    value: label,
    onChange: e => setLabel(e.target.value),
    onBlur: submit,
    onKeyDown: e => e.key === "Enter" && (e.preventDefault(), submit())
  }), /*#__PURE__*/React.createElement("p", {
    className: "bb-caption",
    style: {
      marginTop: 6
    }
  }, "Incoming ", /*#__PURE__*/React.createElement("b", null, node.relationCounts.up), " \xB7 Outgoing ", /*#__PURE__*/React.createElement("b", null, node.relationCounts.down))), /*#__PURE__*/React.createElement("div", {
    className: "bb-grid2"
  }, /*#__PURE__*/React.createElement("section", {
    className: "bb-subcard"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-label"
  }, /*#__PURE__*/React.createElement(I.Layers, {
    size: 14
  }), " Type"), /*#__PURE__*/React.createElement("select", {
    className: "bb-input",
    value: nodeType,
    onChange: e => setNodeType(e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "parent"
  }, "Parent"), /*#__PURE__*/React.createElement("option", {
    value: "child"
  }, "Child"))), /*#__PURE__*/React.createElement("section", {
    className: "bb-subcard"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-label"
  }, /*#__PURE__*/React.createElement(I.Spark, {
    size: 14
  }), " Highlight"), /*#__PURE__*/React.createElement("select", {
    className: "bb-input",
    defaultValue: "none"
  }, /*#__PURE__*/React.createElement("option", {
    value: "none"
  }, "None"), /*#__PURE__*/React.createElement("option", {
    value: "cause_candidate"
  }, "Cause candidate"), /*#__PURE__*/React.createElement("option", {
    value: "effect_spanning"
  }, "Effect spanning")))), /*#__PURE__*/React.createElement("section", {
    className: "bb-subcard"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-label"
  }, /*#__PURE__*/React.createElement(I.Shield, {
    size: 14
  }), " Validation"), /*#__PURE__*/React.createElement("p", {
    className: "bb-caption",
    style: {
      marginTop: 2
    }
  }, "Run validation against the selected provider and review history."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      alignItems: "center",
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Shield, {
      size: 14
    }),
    onClick: () => onValidate(node.id)
  }, "Run validation"), /*#__PURE__*/React.createElement("span", {
    className: "bb-micro"
  }, "Uses the mock provider when none configured.")), validations.length > 0 ? /*#__PURE__*/React.createElement("ul", {
    className: "bb-validations"
  }, validations.slice(-3).reverse().map((v, i) => /*#__PURE__*/React.createElement("li", {
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("b", null, v.confidence, "%"), /*#__PURE__*/React.createElement("span", {
    className: "bb-micro"
  }, v.time)), /*#__PURE__*/React.createElement("p", {
    className: "bb-caption"
  }, v.summary)))) : /*#__PURE__*/React.createElement("div", {
    className: "bb-empty-dash"
  }, "No previous validations recorded.")), /*#__PURE__*/React.createElement("section", {
    className: "bb-ai-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-label",
    style: {
      color: "#047857"
    }
  }, /*#__PURE__*/React.createElement(I.Spark, {
    size: 14
  }), " AI feedback"), /*#__PURE__*/React.createElement("p", {
    className: "bb-caption",
    style: {
      color: "#065f46",
      marginTop: 2
    }
  }, "Request a quick summary and recommendations."), /*#__PURE__*/React.createElement("label", {
    className: "bb-consent"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: consent,
    onChange: e => setConsent(e.target.checked)
  }), /*#__PURE__*/React.createElement("span", null, "I consent to send the current tree to the AI provider for analysis.")), /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Spark, {
      size: 14
    }),
    disabled: !consent,
    className: "bb-emerald"
  }, "Request feedback")), /*#__PURE__*/React.createElement(Button, {
    variant: "danger",
    size: "sm",
    leftIcon: /*#__PURE__*/React.createElement(I.Trash, {
      size: 14
    }),
    onClick: () => onDelete(node.id),
    className: "bb-full"
  }, "Delete node"));
};
const InspectorPlaceholder = ({
  message
}) => /*#__PURE__*/React.createElement("div", {
  className: "bb-placeholder"
}, /*#__PURE__*/React.createElement(I.Sprout, {
  size: 24,
  stroke: "#94a3b8"
}), /*#__PURE__*/React.createElement("p", null, message));

// ---------- Toast ----------
const Toast = ({
  toast,
  onDismiss
}) => {
  const icons = {
    success: /*#__PURE__*/React.createElement(I.Check, {
      size: 16
    }),
    info: /*#__PURE__*/React.createElement(I.Info, {
      size: 16
    }),
    warning: /*#__PURE__*/React.createElement(I.Alert, {
      size: 16
    }),
    error: /*#__PURE__*/React.createElement(I.AlertC, {
      size: 16
    })
  };
  return /*#__PURE__*/React.createElement("div", {
    className: `bb-toast variant-${toast.variant}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-toast-icon"
  }, icons[toast.variant]), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-toast-title"
  }, toast.title), toast.description && /*#__PURE__*/React.createElement("div", {
    className: "bb-toast-desc"
  }, toast.description)), /*#__PURE__*/React.createElement("button", {
    className: "bb-toast-close",
    onClick: () => onDismiss(toast.id),
    "aria-label": "Dismiss"
  }, /*#__PURE__*/React.createElement(I.X, {
    size: 14
  })));
};

// ---------- Modal ----------
const Modal = ({
  open,
  title,
  children,
  onClose
}) => {
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "bb-modal-backdrop",
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-modal",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    className: "bb-modal-title"
  }, title), children));
};

// ---------- Auth layout ----------
const AuthShell = ({
  title,
  children
}) => /*#__PURE__*/React.createElement("div", {
  className: "bb-auth-shell"
}, /*#__PURE__*/React.createElement("div", {
  className: "bb-auth-card"
}, /*#__PURE__*/React.createElement("div", {
  className: "bb-auth-brand"
}, /*#__PURE__*/React.createElement(I.Sprout, {
  size: 22
}), /*#__PURE__*/React.createElement("span", null, "Brain Buddy")), /*#__PURE__*/React.createElement("h1", {
  className: "bb-auth-title"
}, title), children));
Object.assign(window, {
  I,
  Icon,
  Button,
  BrainNode,
  Canvas,
  Edges,
  Dropdown,
  MenuItem,
  TreeMenu,
  Inspector,
  InspectorPlaceholder,
  Toast,
  Modal,
  AuthShell
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/workspace/components.jsx", error: String((e && e.message) || e) }); }

})();
