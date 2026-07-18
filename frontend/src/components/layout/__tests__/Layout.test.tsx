import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Layout } from "../Layout";
import { useTreeStore } from "../../../stores/treeStore";

describe("Layout beforeunload guard", () => {
  beforeEach(() => {
    useTreeStore.getState().reset();
  });
  afterEach(() => {
    cleanup();
    act(() => {
      useTreeStore.getState().reset();
    });
    vi.restoreAllMocks();
  });

  it("does not prevent unload when there are no pending changes", () => {
    render(
      <Layout header={<div>Header</div>} sidebar={<div>Sidebar</div>}>
        <div>Content</div>
      </Layout>
    );
    const event = new Event("beforeunload");
    const spy = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(spy).not.toHaveBeenCalled();
  });

  it("prevents unload when there are pending sync changes", () => {
    act(() => {
      useTreeStore.setState({ activeTreeId: "t1", pendingSync: true });
    });

    render(
      <Layout header={<div>Header</div>} sidebar={<div>Sidebar</div>}>
        <div>Content</div>
      </Layout>
    );
    const event = new Event("beforeunload");
    const spy = vi.spyOn(event, "preventDefault");
    act(() => window.dispatchEvent(event));
    expect(spy).toHaveBeenCalled();
  });

  it("renders an optional footer when provided", () => {
    render(
      <Layout header={<div>Header</div>} sidebar={<div>Sidebar</div>} footer={<div>Footer text</div>}>
        <div>Content</div>
      </Layout>
    );
    expect(screen.getByText("Footer text")).toBeInTheDocument();
  });
});
