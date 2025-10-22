import { useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  ReactFlowProvider
} from "reactflow";
import "reactflow/dist/style.css";

import { CreateNodeButton } from "./components/CreateNodeButton";

const initialNodes: Node[] = [
  {
    id: "root",
    position: { x: 0, y: 0 },
    data: { label: "Brain Buddy" },
    type: "default"
  }
];

export default function App(): JSX.Element {
  const [nodes, setNodes] = useState(initialNodes);
  const edges = useMemo(() => [], []);

  return (
    <ReactFlowProvider>
      <main className="app-shell">
        <aside className="panel">
          <h1 className="panel__title">Brain Buddy</h1>
          <p className="panel__description">
            React Flow workspace scaffold. Replace with canvas and inspector
            implementations in Phase 1.
          </p>
          <CreateNodeButton onCreate={(node) => setNodes((prev) => [...prev, node])} />
        </aside>
        <section className="canvas">
          <ReactFlow nodes={nodes} edges={edges} fitView>
            <MiniMap />
            <Controls />
            <Background gap={16} size={1} />
          </ReactFlow>
        </section>
      </main>
    </ReactFlowProvider>
  );
}
