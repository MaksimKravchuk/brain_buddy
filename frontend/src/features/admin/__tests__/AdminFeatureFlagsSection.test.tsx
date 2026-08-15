import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AdminFeatureFlagState,
  AdminFeatureFlagsResponse
} from "../../../api/adminTypes";
import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AdminFeatureFlagsSection } from "../AdminFeatureFlagsSection";
import { focusFirstAvailable } from "../flagFocus";

const VOICE = "voice_brain_dump";
const MOBILE = "mobile_task_classification";

function flag(overrides: Partial<AdminFeatureFlagState> = {}): AdminFeatureFlagState {
  return {
    name: VOICE,
    override_mode: null,
    source: "deploy_default",
    deploy_default_state: "off",
    selected_users: [],
    ...overrides
  };
}

function response(
  flags: AdminFeatureFlagState[],
  degraded = false
): AdminFeatureFlagsResponse {
  return { degraded, flags };
}

const bothFlags = (voice: Partial<AdminFeatureFlagState> = {}) =>
  response([flag(voice), flag({ name: MOBILE })]);

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminFeatureFlagsSection />
    </QueryClientProvider>
  );
}

const row = (name: string) => screen.getByRole("article", { name });

/** Render the section and wait for `F-02`, the state most tests start from. */
async function ready(name = VOICE) {
  renderSection();
  await screen.findByRole("article", { name });
  return row(name);
}

beforeEach(() => {
  // The query is owner-scoped and only enabled for an authenticated caller, so
  // the store has to name one — exactly as `AdminPage` does in production.
  act(() => {
    useAuthStore.setState({
      user: { id: "operator-1", email: "operator@example.com" },
      status: "authed",
      deletionCancelledNotice: false
    });
  });
  // Every mutation spy is installed per test; the read is the only shared one.
  vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(bothFlags());
});

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    useAuthStore.setState({ user: null, status: "anon", deletionCancelledNotice: false });
  });
});

describe("AdminFeatureFlagsSection (010-FR-010, design F-01…F-13)", () => {
  it("010-FR-010: F-01 renders a loading status and no controls while the read is in flight", () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockReturnValue(new Promise(() => {}));

    renderSection();

    expect(screen.getByRole("status")).toHaveTextContent(/loading feature flags/i);
    // A mode can never be changed against an unknown current state.
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("010-FR-003: F-02 shows no checked radio while inheriting, with the deploy state as its own value", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: null, source: "deploy_default", deploy_default_state: "internal" })
    );

    const voice = await ready();

    for (const name of ["Off", "On", "Selected users"]) {
      expect(within(voice).getByRole("radio", { name })).not.toBeChecked();
    }
    expect(within(voice).getByText(/deploy default \(internal\)/i)).toBeInTheDocument();
    // An inherited `internal` baseline is never mapped onto one of the three
    // override radios (DD-3) — and there is nothing to clear.
    expect(
      within(voice).queryByRole("button", { name: /use deploy default/i })
    ).not.toBeInTheDocument();
  });

  it("010-FR-010: F-02 checks exactly the overridden mode and offers the clear action", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "on", source: "runtime", deploy_default_state: "internal" })
    );

    const voice = await ready();

    expect(within(voice).getByRole("radio", { name: "On" })).toBeChecked();
    expect(within(voice).getByRole("radio", { name: "Off" })).not.toBeChecked();
    expect(within(voice).getByText(/runtime override/i)).toBeInTheDocument();
    // Never hidden merely because an override is active: the operator must see
    // what "Use deploy default" would fall back to before clicking it (DD-3).
    expect(within(voice).getByText(/deploy default: internal/i)).toBeInTheDocument();
    expect(
      within(voice).getByRole("button", { name: /use deploy default/i })
    ).toBeInTheDocument();
  });

  it("010-FR-010: the mode control is a native fieldset/legend radio group", async () => {
    const voice = await ready();

    const group = within(voice).getByRole("group", { name: new RegExp(`${VOICE} mode`, "i") });
    expect(group.tagName).toBe("FIELDSET");
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
  });

  it("010-FR-005: F-03 keeps the retained cohort count visible while the mode is on", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "on",
        source: "runtime",
        selected_users: [{ account_id: "user_a", email: "a@example.com" }]
      })
    );

    const voice = await ready();

    expect(within(voice).getByText("1 selected")).toBeInTheDocument();
    // F-04/F-06 stay hidden outside SELECTED_USERS mode — only the count shows.
    expect(within(voice).queryByRole("button", { name: /^remove/i })).not.toBeInTheDocument();
    expect(within(voice).queryByLabelText(/account id or email/i)).not.toBeInTheDocument();
  });

  it("010-FR-010: F-04 gives each Remove action an accessible name carrying the row identity", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [
          { account_id: "user_a", email: "a@example.com" },
          { account_id: "user_b", email: "b@example.com" }
        ]
      })
    );

    const voice = await ready();

    expect(within(voice).getByText("2 selected")).toBeInTheDocument();
    expect(within(voice).getByRole("button", { name: "Remove a@example.com" })).toBeInTheDocument();
    expect(within(voice).getByRole("button", { name: "Remove b@example.com" })).toBeInTheDocument();
    expect(within(voice).getByText("user_a")).toBeInTheDocument();
  });

  it("010-FR-010: F-05 states the consequence when a selected-users cohort is empty", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );

    const voice = await ready();

    expect(within(voice).getByText(/no users selected — this flag is off for everyone/i)).toBeInTheDocument();
    expect(within(voice).getByText("0 selected")).toBeInTheDocument();
  });

  it("010-FR-007: F-06 renders the add form only in selected-users mode", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );

    const voice = await ready();

    expect(within(voice).getByLabelText(/account id or email/i)).toBeInTheDocument();
    expect(within(voice).getByRole("button", { name: "Add" })).toBeInTheDocument();
    expect(
      within(row(MOBILE)).queryByLabelText(/account id or email/i)
    ).not.toBeInTheDocument();
  });

  it("010-FR-007: F-07 shows 009's own no-match copy and adds nobody", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );
    const add = vi
      .spyOn(apiClient, "addAdminFeatureFlagUser")
      .mockRejectedValue(new ApiError("Not Found", 404, { message: "No account found." }));

    const voice = await ready();
    await userEvent.type(within(voice).getByLabelText(/account id or email/i), "ghost@example.com");
    await userEvent.click(within(voice).getByRole("button", { name: "Add" }));

    expect(await within(voice).findByText("No account found.")).toBeInTheDocument();
    expect(add).toHaveBeenCalledWith(VOICE, { email: "ghost@example.com" });
    expect(within(voice).getByText("0 selected")).toBeInTheDocument();
  });

  it("010-FR-010: F-08 → F-09 re-renders from the server's response, never optimistic state", async () => {
    const set = vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockResolvedValue(
      // The server answers `selected_users`, not the `on` that was clicked: the
      // row must show what the server stored, not what the operator asked for.
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "On" }));

    expect(set).toHaveBeenCalledWith(VOICE, "on");
    expect(await within(voice).findByText("Saved.")).toBeInTheDocument();
    expect(within(voice).getByRole("radio", { name: "Selected users" })).toBeChecked();
    expect(within(voice).getByRole("radio", { name: "On" })).not.toBeChecked();
  });

  it("010-FR-010: F-08a confirms exactly the three allowlisted mutations and nothing else", async () => {
    const cohort = (
      members: Array<{ account_id: string; email: string | null }>,
      mode: "selected_users" | "on" = "selected_users"
    ) =>
      bothFlags({
        override_mode: mode,
        source: "runtime",
        deploy_default_state: "internal",
        selected_users: members
      });
    const a = { account_id: "user_a", email: "a@example.com" };
    const b = { account_id: "user_b", email: "b@example.com" };
    const c = { account_id: "user_c", email: "c@example.com" };

    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(cohort([a, b]));
    const remove = vi
      .spyOn(apiClient, "removeAdminFeatureFlagUser")
      .mockResolvedValue(cohort([b]));
    const add = vi
      .spyOn(apiClient, "addAdminFeatureFlagUser")
      .mockResolvedValue(cohort([b, c]));
    const set = vi
      .spyOn(apiClient, "setAdminFeatureFlagMode")
      .mockResolvedValue(cohort([b, c], "on"));

    const voice = await ready();

    // Immediate: removing a non-last member.
    await userEvent.click(within(voice).getByRole("button", { name: "Remove a@example.com" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(remove).toHaveBeenCalledWith(VOICE, "user_a");

    // Immediate: adding a user.
    await userEvent.type(within(row(VOICE)).getByLabelText(/account id or email/i), "user_c");
    await userEvent.click(within(row(VOICE)).getByRole("button", { name: "Add" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(add).toHaveBeenCalledWith(VOICE, { account_id: "user_c" });

    // Immediate: ON.
    await userEvent.click(within(row(VOICE)).getByRole("radio", { name: "On" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(set).toHaveBeenCalledWith(VOICE, "on");

    // Immediate: SELECTED_USERS.
    await userEvent.click(within(row(VOICE)).getByRole("radio", { name: "Selected users" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(set).toHaveBeenCalledWith(VOICE, "selected_users");
  });

  it("010-FR-010: F-08a gates setting a flag OFF behind a confirmation", async () => {
    const set = vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockResolvedValue(
      bothFlags({ override_mode: "off", source: "runtime" })
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "Off" }));

    expect(set).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(new RegExp(`Turn ${VOICE} off for everyone`, "i"))).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(VOICE, "off"));
  });

  it("010-FR-010: F-08a gates removing the last remaining cohort member", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [{ account_id: "user_a", email: "a@example.com" }]
      })
    );
    const remove = vi
      .spyOn(apiClient, "removeAdminFeatureFlagUser")
      .mockResolvedValue(bothFlags({ override_mode: "selected_users", source: "runtime" }));

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("button", { name: "Remove a@example.com" }));

    expect(remove).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        new RegExp(`remove the last selected user\\? ${VOICE} will be off for everyone`, "i")
      )
    ).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Remove user" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(VOICE, "user_a"));
  });

  it("010-FR-010: F-08a gates clearing a runtime override and previews the deploy default", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "on", source: "runtime", deploy_default_state: "internal" })
    );
    const clear = vi
      .spyOn(apiClient, "clearAdminFeatureFlagOverride")
      .mockResolvedValue(bothFlags({ deploy_default_state: "internal" }));

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("button", { name: /use deploy default/i }));

    expect(clear).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/it currently ships internal/i)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Use deploy default" }));
    await waitFor(() => expect(clear).toHaveBeenCalledWith(VOICE));
  });

  it("010-SC-008: F-08a is dismissible by Escape and by Cancel, restoring focus each time", async () => {
    const set = vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockResolvedValue(bothFlags());

    const voice = await ready();
    const trigger = within(voice).getByRole("radio", { name: "Off" });

    await userEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    // The confirm receives focus on appearance, so a keyboard user is not left
    // behind the dialog they just opened.
    expect(dialog.contains(document.activeElement)).toBe(true);

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(trigger);

    await userEvent.click(trigger);
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.activeElement).toBe(trigger);
    expect(set).not.toHaveBeenCalled();
  });

  it("010-SC-008: F-09 moves focus to the next remaining Remove action after a row removal", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [
          { account_id: "user_a", email: "a@example.com" },
          { account_id: "user_b", email: "b@example.com" }
        ]
      })
    );
    vi.spyOn(apiClient, "removeAdminFeatureFlagUser").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [{ account_id: "user_b", email: "b@example.com" }]
      })
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("button", { name: "Remove a@example.com" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(row(VOICE)).getByRole("button", { name: "Remove b@example.com" })
      )
    );
  });

  it("010-SC-008: F-09 falls back to the add input, then the count region, as rows run out", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [{ account_id: "user_a", email: "a@example.com" }]
      })
    );
    vi.spyOn(apiClient, "removeAdminFeatureFlagUser").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("button", { name: "Remove a@example.com" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove user" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(row(VOICE)).getByLabelText(/account id or email/i)
      )
    );
  });

  it("010-SC-008: F-09's fallback chain ends at the cohort-count region, in order", () => {
    // The last link is unreachable through the rendered UI — the add-user input
    // is always present in SELECTED_USERS mode, which is the only mode that
    // renders a removable row — so the ordering is asserted on the helper that
    // implements it rather than left as a fallback nothing exercises.
    const first = document.createElement("button");
    const second = document.createElement("input");
    const third = document.createElement("p");
    third.tabIndex = -1;
    document.body.append(first, second, third);

    expect(focusFirstAvailable([first, second, third])).toBe(first);
    expect(document.activeElement).toBe(first);
    expect(focusFirstAvailable([null, second, third])).toBe(second);
    expect(document.activeElement).toBe(second);
    expect(focusFirstAvailable([null, undefined, third])).toBe(third);
    expect(document.activeElement).toBe(third);
    expect(focusFirstAvailable([null, undefined, null])).toBeNull();

    first.remove();
    second.remove();
    third.remove();
  });

  it("010-FR-010: F-09 returns focus to the triggering control after a mode change", async () => {
    vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockResolvedValue(
      bothFlags({ override_mode: "on", source: "runtime" })
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "On" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(within(row(VOICE)).getByRole("radio", { name: "On" }))
    );
  });

  it("010-SC-008: F-10 surfaces the correlation ID and reverts to the last server-confirmed state", async () => {
    vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockRejectedValue(
      new ApiError("Server Error", 500, { message: "Internal storage error." }, "corr-123")
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "On" }));

    const alert = await within(row(VOICE)).findByRole("alert");
    expect(alert).toHaveTextContent(/corr-123/);
    // The row shows the server's last confirmed answer, not the click.
    expect(within(row(VOICE)).getByRole("radio", { name: "On" })).not.toBeChecked();
  });

  it("010-SC-008: F-10 uses named fallback copy when no response was received at all", async () => {
    vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockRejectedValue(
      new TypeError("Failed to fetch")
    );

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "On" }));

    const alert = await within(row(VOICE)).findByRole("alert");
    expect(alert).toHaveTextContent(
      "Could not reach the server. Check your connection and try again."
    );
    expect(alert).not.toHaveTextContent(/ref:/);
  });

  it("010-SC-008: F-11 disables every control on a degraded store and offers no reset", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      response([flag({ override_mode: "on", source: "runtime" }), flag({ name: MOBILE })], true)
    );

    const voice = await ready();

    expect(
      screen.getByText(/runtime flag state could not be read/i)
    ).toBeInTheDocument();
    for (const radio of within(voice).getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
    expect(within(voice).getByRole("button", { name: /use deploy default/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reset/i })).not.toBeInTheDocument();
  });

  it("010-FR-007: F-12 renders an unresolvable stored ID and keeps it removable", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [{ account_id: "user_gone", email: null }]
      })
    );
    const remove = vi
      .spyOn(apiClient, "removeAdminFeatureFlagUser")
      .mockResolvedValue(bothFlags({ override_mode: "selected_users", source: "runtime" }));

    const voice = await ready();

    expect(within(voice).getByText("Account not found")).toBeInTheDocument();
    const button = within(voice).getByRole("button", { name: "Remove user_gone" });
    await userEvent.click(button);
    await userEvent.click(await screen.findByRole("button", { name: "Remove user" }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith(VOICE, "user_gone"));
  });

  it("010-SC-008: F-13 distinguishes a failed initial read from a degraded store, with a retry", async () => {
    const read = vi
      .spyOn(apiClient, "getAdminFeatureFlags")
      .mockRejectedValueOnce(new ApiError("Server Error", 503, null, "corr-9"))
      .mockResolvedValueOnce(bothFlags());

    renderSection();

    expect(await screen.findByText(/couldn't load feature flags/i)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/corr-9/);
    expect(screen.queryByText(/runtime flag state could not be read/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    await screen.findByRole("article", { name: VOICE });
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("010-FR-007: sends the typed value as typed, classifying it exactly as feature 009 does", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );
    const add = vi.spyOn(apiClient, "addAdminFeatureFlagUser").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );

    const voice = await ready();
    const input = within(voice).getByLabelText(/account id or email/i);

    // `admin@localhost` classifies as an email — a dotted-domain pattern would
    // report a real (possibly operator) account missing.
    await userEvent.type(input, "admin@localhost");
    await userEvent.click(within(voice).getByRole("button", { name: "Add" }));
    expect(add).toHaveBeenCalledWith(VOICE, { email: "admin@localhost" });

    // `a@` is malformed rather than an address: it falls through to account_id
    // and yields the no-match state, which is the design's stated behaviour.
    await userEvent.clear(within(row(VOICE)).getByLabelText(/account id or email/i));
    await userEvent.type(within(row(VOICE)).getByLabelText(/account id or email/i), "a@");
    await userEvent.click(within(row(VOICE)).getByRole("button", { name: "Add" }));
    expect(add).toHaveBeenCalledWith(VOICE, { account_id: "a@" });

    // Never trimmed: trimming a whitespace variant into the canonical address
    // would manufacture a match the server is required to refuse (009-FR-003).
    await userEvent.clear(within(row(VOICE)).getByLabelText(/account id or email/i));
    await userEvent.type(within(row(VOICE)).getByLabelText(/account id or email/i), " user_a ");
    await userEvent.click(within(row(VOICE)).getByRole("button", { name: "Add" }));
    expect(add).toHaveBeenCalledWith(VOICE, { account_id: " user_a " });
  });

  it("010-FR-010: an empty add submission sends nothing", async () => {
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({ override_mode: "selected_users", source: "runtime" })
    );
    const add = vi.spyOn(apiClient, "addAdminFeatureFlagUser").mockResolvedValue(bothFlags());

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("button", { name: "Add" }));

    expect(add).not.toHaveBeenCalled();
  });

  it("010-FR-010: a mutation on one flag leaves the other flag's controls usable", async () => {
    vi.spyOn(apiClient, "setAdminFeatureFlagMode").mockReturnValue(new Promise(() => {}));

    const voice = await ready();
    await userEvent.click(within(voice).getByRole("radio", { name: "On" }));

    expect(within(row(VOICE)).getByRole("radio", { name: "On" })).toBeDisabled();
    expect(within(row(MOBILE)).getByRole("radio", { name: "On" })).toBeEnabled();
  });

  it("010-SC-008: the section reflows to the stated stacked layout at 390×851", async () => {
    // jsdom has no layout engine, so a measured height is always zero. What is
    // checkable — and what design.md's "Mobile reflow at 390×851" section
    // actually states — is the treatment: the mode fieldset, source note,
    // cohort rows and confirm controls stack rather than sitting side by side,
    // and every tappable control carries the 44px minimum.
    window.innerWidth = 390;
    window.innerHeight = 851;
    vi.spyOn(apiClient, "getAdminFeatureFlags").mockResolvedValue(
      bothFlags({
        override_mode: "selected_users",
        source: "runtime",
        selected_users: [{ account_id: "user_a", email: "a@example.com" }]
      })
    );

    const voice = await ready();

    const group = within(voice).getByRole("group", { name: new RegExp(`${VOICE} mode`, "i") });
    expect(group.className).toMatch(/flex-wrap/);
    expect(within(voice).getByTestId(`source-note-${VOICE}`).className).toMatch(/flex-col/);
    expect(within(voice).getByTestId(`cohort-row-user_a`).className).toMatch(/flex-col/);
    expect(within(voice).getByTestId(`add-form-${VOICE}`).className).toMatch(/flex-col/);
    expect(
      within(voice).getByRole("button", { name: "Remove a@example.com" }).className
    ).toMatch(/min-h-\[44px\]/);

    await userEvent.click(within(voice).getByRole("button", { name: "Remove a@example.com" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("confirm-actions").className).toMatch(/flex-col/);
    for (const name of ["Cancel", "Remove user"]) {
      expect(within(dialog).getByRole("button", { name }).className).toMatch(/min-h-\[44px\]/);
    }
  });
});
