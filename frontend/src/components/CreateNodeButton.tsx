import { useCallback } from "react";
import type { Node } from "reactflow";
import { twMerge } from "tailwind-merge";

import { buttonVariants } from "../styles/buttonVariants";

interface CreateNodeButtonProps {
  onCreate: (node: Node) => void;
}

let counter = 0;

export function CreateNodeButton({ onCreate }: CreateNodeButtonProps): JSX.Element {
  const handleClick = useCallback(() => {
    counter += 1;
    onCreate({
      id: `node-${counter}`,
      position: { x: counter * 40, y: counter * 20 },
      data: { label: `Node ${counter}` }
    });
  }, [onCreate]);

  return (
    <button
      type="button"
      className={twMerge(buttonVariants({ intent: "primary" }), "w-full")}
      onClick={handleClick}
    >
      Add Node
    </button>
  );
}
