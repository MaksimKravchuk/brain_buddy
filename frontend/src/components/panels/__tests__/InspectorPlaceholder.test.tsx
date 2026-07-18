import { Circle } from "lucide-react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InspectorPlaceholder } from "../InspectorPlaceholder";

describe("InspectorPlaceholder", () => {
  it("explains that no inspector target is selected with the default icon", () => {
    render(<InspectorPlaceholder message="Select a node to inspect it." />);

    expect(screen.getByText("Select a node to inspect it.")).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeInTheDocument();
  });

  it("renders a supplied icon beside the selection guidance", () => {
    render(<InspectorPlaceholder message="Choose a relation." icon={Circle} />);

    expect(document.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByText("Choose a relation.")).toBeInTheDocument();
  });
});
