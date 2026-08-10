import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { BrainDumpOverlay, BrainDumpOverlayHeader } from "./BrainDumpOverlay";
import { useCloseBrainDump } from "./brainDumpNavigation";

function renderOverlay(props: Partial<Parameters<typeof BrainDumpOverlay>[0]> = {}) {
  const onClose = props.onClose === undefined && !("onClose" in props) ? vi.fn() : props.onClose;
  const view = render(
    <BrainDumpOverlay labelledBy="panel-title" onClose={onClose} {...props}>
      <h1 id="panel-title">Brain dump</h1>
      <button type="button">first</button>
      <button type="button">last</button>
    </BrainDumpOverlay>
  );
  return { ...view, onClose };
}

describe("BrainDumpOverlay", () => {
  it("presents the panel as a modal dialog and takes focus so the keyboard lands inside it", () => {
    renderOverlay();

    const dialog = screen.getByRole("dialog", { name: "Brain dump" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveFocus();
  });

  it("closes on Escape and on a click outside the panel when the overlay is dismissible", async () => {
    const user = userEvent.setup();
    const { onClose } = renderOverlay();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId("brain-dump-scrim"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("offers no way out while the overlay is not dismissible, so a live capture cannot be abandoned", async () => {
    const user = userEvent.setup();
    renderOverlay({ onClose: undefined });

    expect(screen.queryByTestId("brain-dump-scrim")).not.toBeInTheDocument();

    // Escape must be inert rather than throwing or unmounting the panel.
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Brain dump" })).toBeInTheDocument();
  });

  it("ignores keys that are neither Escape nor Tab", async () => {
    const user = userEvent.setup();
    const { onClose } = renderOverlay();

    await user.keyboard("a");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cycles Tab inside the panel so focus never reaches the workspace behind it", async () => {
    const user = userEvent.setup();
    renderOverlay();
    const first = screen.getByRole("button", { name: "first" });
    const last = screen.getByRole("button", { name: "last" });

    // Shift+Tab from the freshly focused panel wraps to the end.
    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    // Forward from the end wraps back to the start.
    await user.tab();
    expect(first).toHaveFocus();

    // And backwards from the start wraps to the end again.
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
  });

  it("moves focus normally between interior controls without hijacking every Tab", async () => {
    const user = userEvent.setup();
    renderOverlay();

    screen.getByRole("button", { name: "first" }).focus();
    await user.tab();

    expect(screen.getByRole("button", { name: "last" })).toHaveFocus();
  });

  it("leaves Tab alone when the panel holds nothing focusable", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <BrainDumpOverlay labelledBy="empty-title" onClose={onClose}>
        <h1 id="empty-title">Saving tasks</h1>
      </BrainDumpOverlay>
    );

    await user.tab();

    expect(screen.getByRole("dialog", { name: "Saving tasks" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("sizes the panel wide by default and narrow on request", () => {
    const { unmount } = renderOverlay();
    expect(screen.getByRole("dialog", { name: "Brain dump" }).className).toContain("sm:w-[880px]");
    unmount();

    renderOverlay({ size: "narrow" });
    expect(screen.getByRole("dialog", { name: "Brain dump" }).className).toContain("sm:w-[480px]");
  });

  it("stamps the operation id on the panel for end-to-end assertions", () => {
    renderOverlay({ operationId: "brain_dump_7" });

    expect(screen.getByRole("dialog", { name: "Brain dump" })).toHaveAttribute("data-operation-id", "brain_dump_7");
  });

  it("locks workspace scrolling while open and restores the previous value on unmount", () => {
    document.body.style.overflow = "scroll";

    const { unmount } = renderOverlay();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("scroll");

    document.body.style.overflow = "";
  });
});

describe("BrainDumpOverlayHeader", () => {
  it("renders the eyebrow, meta and close affordance when they are supplied", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <BrainDumpOverlayHeader
        titleId="header-title"
        eyebrow="Brain dump"
        title="Review 3 tasks"
        meta="Edit before they land in your inbox"
        status={<span>Recording</span>}
        onClose={onClose}
      />
    );

    expect(screen.getByRole("heading", { name: "Review 3 tasks" })).toHaveAttribute("id", "header-title");
    expect(screen.getByText("Brain dump")).toBeInTheDocument();
    expect(screen.getByText("Edit before they land in your inbox")).toBeInTheDocument();
    expect(screen.getByText("Recording")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close brain dump" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("omits the eyebrow, meta and close affordance when they are not supplied", () => {
    render(<BrainDumpOverlayHeader titleId="bare-title" title="Sealing audio" />);

    expect(screen.getByRole("heading", { name: "Sealing audio" })).toBeInTheDocument();
    expect(screen.queryByText("Brain dump")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close brain dump" })).not.toBeInTheDocument();
  });
});

function CloseTrigger() {
  const close = useCloseBrainDump();
  return (
    <button type="button" onClick={close}>
      close overlay
    </button>
  );
}

function RouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="current route">{location.pathname}</output>
      <button type="button" onClick={() => navigate(-1)}>
        go back
      </button>
    </>
  );
}

function renderCloseHarness(entries: Parameters<typeof MemoryRouter>[0]["initialEntries"], initialIndex: number) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={initialIndex}>
      <RouteProbe />
      <Routes>
        <Route path="/tasks/:state" element={<span>task list</span>} />
        <Route path="/brain-dump/:operationId" element={<CloseTrigger />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("useCloseBrainDump", () => {
  it("steps back to the view the overlay was opened over", async () => {
    const user = userEvent.setup();
    renderCloseHarness(
      [
        { pathname: "/tasks/waiting" },
        { pathname: "/brain-dump/new", state: { backgroundLocation: { pathname: "/tasks/waiting" } } }
      ],
      1
    );

    await user.click(screen.getByRole("button", { name: "close overlay" }));

    expect(screen.getByLabelText("current route")).toHaveTextContent("/tasks/waiting");
  });

  it("falls back to the default list when the overlay was opened directly, with nothing behind it", async () => {
    const user = userEvent.setup();
    renderCloseHarness([{ pathname: "/brain-dump/new" }], 0);

    await user.click(screen.getByRole("button", { name: "close overlay" }));

    expect(screen.getByLabelText("current route")).toHaveTextContent("/tasks/next");
  });

  it("replaces the deep-linked overlay in history rather than stacking on top of it", async () => {
    const user = userEvent.setup();
    renderCloseHarness([{ pathname: "/brain-dump/new" }], 0);

    await user.click(screen.getByRole("button", { name: "close overlay" }));
    await user.click(screen.getByRole("button", { name: "go back" }));

    // Back must not resurrect the panel the user just dismissed.
    expect(screen.getByLabelText("current route")).toHaveTextContent("/tasks/next");
    expect(screen.queryByRole("button", { name: "close overlay" })).not.toBeInTheDocument();
  });
});
