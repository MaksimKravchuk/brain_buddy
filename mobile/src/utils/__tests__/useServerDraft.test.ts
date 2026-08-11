import { act, renderHook } from "@testing-library/react-native";

import { useServerDraft } from "../useServerDraft";

/** Render the hook with an explicit key, as the task screen does. */
function renderKeyed(value: string, key: string) {
  return renderHook(
    ({ value: v, key: k }: { value: string; key: string }) => useServerDraft(v, k),
    { initialProps: { value, key } },
  );
}

describe("useServerDraft", () => {
  it("shows the server value until the user types", async () => {
    const { result } = await renderKeyed("Call the notary", "r1");
    expect(result.current[0]).toBe("Call the notary");

    await act(() => result.current[1]("Call the notary tomorrow"));
    expect(result.current[0]).toBe("Call the notary tomorrow");
  });

  it("keeps the edit while the key is unchanged, even as the server value moves", async () => {
    const { result, rerender } = await renderKeyed("Draft", "r1");

    await act(() => result.current[1]("Mine"));
    await rerender({ value: "Theirs", key: "r1" });

    expect(result.current[0]).toBe("Mine");
  });

  it("abandons the edit as soon as a new key arrives", async () => {
    const { result, rerender } = await renderKeyed("Draft", "r1");

    await act(() => result.current[1]("Mine"));
    await rerender({ value: "Reconciled", key: "r2" });

    expect(result.current[0]).toBe("Reconciled");
  });

  it("lets the user edit again after the key moved on", async () => {
    const { result, rerender } = await renderKeyed("Draft", "r1");

    await act(() => result.current[1]("Mine"));
    await rerender({ value: "Reconciled", key: "r2" });
    await act(() => result.current[1]("Mine again"));

    expect(result.current[0]).toBe("Mine again");
  });

  it("defaults the key to the server value, so any server change wins", async () => {
    const { result, rerender } = await renderHook(
      ({ value }: { value: string }) => useServerDraft(value),
      { initialProps: { value: "Buy milk" } },
    );

    await act(() => result.current[1]("Buy oat milk"));
    expect(result.current[0]).toBe("Buy oat milk");

    await rerender({ value: "Buy milk and eggs" });
    expect(result.current[0]).toBe("Buy milk and eggs");
  });

  it("treats an edit back to the server value as an edit, not as a reset", async () => {
    const { result, rerender } = await renderKeyed("Original", "r1");

    await act(() => result.current[1]("Original"));
    await rerender({ value: "Server moved", key: "r1" });

    expect(result.current[0]).toBe("Original");
  });

  it("shows an emptied draft rather than falling back to the server value", async () => {
    const { result } = await renderKeyed("Something", "r1");

    await act(() => result.current[1](""));

    expect(result.current[0]).toBe("");
  });

  it("restores the draft when its own key comes back around", async () => {
    const { result, rerender } = await renderKeyed("First", "r1");

    await act(() => result.current[1]("Mine"));
    await rerender({ value: "Second", key: "r2" });
    expect(result.current[0]).toBe("Second");

    // A draft belongs to the key it was typed under: the edit was made against
    // exactly the value that is on screen again.
    await rerender({ value: "First", key: "r1" });
    expect(result.current[0]).toBe("Mine");
  });

  it("only remembers the most recent draft", async () => {
    const { result, rerender } = await renderKeyed("First", "r1");

    await act(() => result.current[1]("Edit of r1"));
    await rerender({ value: "Second", key: "r2" });
    await act(() => result.current[1]("Edit of r2"));
    await rerender({ value: "First", key: "r1" });

    expect(result.current[0]).toBe("First");
  });
});
