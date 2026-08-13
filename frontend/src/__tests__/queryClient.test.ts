import { afterEach, describe, expect, it } from "vitest";

import { adminKeysFor } from "../api/adminHooks";
// Importing the module is the point: its body constructs the sole
// process-global cache and binds it to auth, exactly once, before React
// renders. A test that built its own QueryClient would prove the helper works
// and prove nothing about production wiring.
import { queryClient } from "../queryClient";
import { useAuthStore } from "../stores/authStore";

const OPERATOR = { id: "operator-1", email: "operator@example.com" };
const operatorStatusKey = adminKeysFor(OPERATOR.id).status();
const unrelatedKey = ["tasks", "next"] as const;

describe("queryClient process wiring (009-FR-005)", () => {
  afterEach(() => {
    // The module-level subscription is permanent by design, so isolation is a
    // matter of resetting the state it reads and the entries it acts on —
    // never of re-binding, which would double the subscriber for later tests.
    useAuthStore.setState({ user: null, status: "loading", deletionCancelledNotice: false });
    queryClient.removeQueries({ queryKey: ["admin"] });
    queryClient.removeQueries({ queryKey: [...unrelatedKey] });
  });

  it("009-FR-005: signing out drops the operator capability entry and nothing else", () => {
    useAuthStore.setState({
      user: OPERATOR,
      status: "authed",
      deletionCancelledNotice: false
    });
    queryClient.setQueryData(operatorStatusKey, { is_operator: true });
    queryClient.setQueryData([...unrelatedKey], { items: [] });
    expect(queryClient.getQueryData(operatorStatusKey)).toEqual({ is_operator: true });

    // The lowest session boundary: the store write itself, not a component
    // unmount. `logout()` and `clearSession()` both land here.
    useAuthStore.getState().clearSession();

    expect(queryClient.getQueryData(operatorStatusKey)).toBeUndefined();
    // Admin-only purge: task/account/relay records survive a session change,
    // matching the existing relay policy rather than clearing the whole cache.
    expect(queryClient.getQueryData([...unrelatedKey])).toEqual({ items: [] });
  });

  it("009-FR-005: the binding is live for an account switch too, not just sign-out", () => {
    useAuthStore.setState({
      user: OPERATOR,
      status: "authed",
      deletionCancelledNotice: false
    });
    queryClient.setQueryData(operatorStatusKey, { is_operator: true });

    useAuthStore.setState({
      user: { id: "member-2", email: "member@example.com" },
      status: "authed",
      deletionCancelledNotice: false
    });

    expect(queryClient.getQueryData(operatorStatusKey)).toBeUndefined();
  });
});
