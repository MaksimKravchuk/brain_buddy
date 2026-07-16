import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Spinner } from "../Spinner";

describe("Spinner", () => {
  it("uses the default loading label and medium size", () => {
    render(<Spinner />);

    expect(screen.getByRole("status", { name: "Loading" })).toHaveClass("h-6", "w-6", "border-2");
  });

  it("uses supplied accessible label and large size", () => {
    render(<Spinner size="lg" label="Saving changes" />);

    expect(screen.getByRole("status", { name: "Saving changes" })).toHaveClass("h-8", "w-8", "border-[3px]");
  });
});
