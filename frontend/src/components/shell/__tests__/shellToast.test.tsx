import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ShellToastContext, useShellToast } from "../shellToast";

function Notifier(): React.JSX.Element {
  const notify = useShellToast();

  return (
    <button type="button" onClick={() => notify("Thinking canvas isn't built yet — placeholder")}>
      Notify
    </button>
  );
}

describe("useShellToast", () => {
  it("delivers the message to the shell that provided the toast sink", async () => {
    const user = userEvent.setup();
    const notify = vi.fn();

    render(
      <ShellToastContext.Provider value={notify}>
        <Notifier />
      </ShellToastContext.Provider>
    );
    await user.click(screen.getByRole("button", { name: "Notify" }));

    expect(notify).toHaveBeenCalledWith("Thinking canvas isn't built yet — placeholder");
  });

  it("is inert outside a shell, so a panel rendered on its own cannot throw on notify", async () => {
    const user = userEvent.setup();

    render(<Notifier />);

    await expect(user.click(screen.getByRole("button", { name: "Notify" }))).resolves.toBeUndefined();
  });
});
