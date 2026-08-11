import { screen, waitFor } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Text } from "react-native";

import { useProjects, useTags } from "@/api/hooks";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";
import { cacheKey } from "@/features/tasks/storageKeys";
import { installFakeBackend, makeMe, type FakeBackend } from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

/**
 * The cache write-through and read-back in `useProjects` / `useTags` — feature
 * 006, FR-006.
 *
 * These paths only run when the network fails, so they are invisible to every
 * happy-path test. They are also the reason the pickers work at all on the
 * train the feature exists for: without a cached list there is nothing to
 * choose from after a cold start with no connection.
 */

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  await AsyncStorage.clear();
});

function Projects() {
  const projects = useProjects();
  return (
    <>
      <Text testID="status">{projects.isError ? "error" : projects.isSuccess ? "ok" : "…"}</Text>
      <Text testID="names">{(projects.data ?? []).map((p) => p.name).join(",")}</Text>
    </>
  );
}

function Tags() {
  const tags = useTags();
  return (
    <>
      <Text testID="status">{tags.isError ? "error" : tags.isSuccess ? "ok" : "…"}</Text>
      <Text testID="names">{(tags.data ?? []).map((t) => t.name).join(",")}</Text>
    </>
  );
}

describe("classification list cache", () => {
  it("006-FR-006 writes the fetched projects through to the device", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "GET /projects": () => [
        { id: "p-1", name: "Q3 planning", color: null, state: "active", revision: 1, open_task_count: 0 },
      ],
    });

    renderWithSession(<Projects />);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ok"));
    await waitFor(async () => {
      const raw = await AsyncStorage.getItem(cacheKey(DEFAULT_SERVER_URL, "user-1"));
      expect(raw).toContain("Q3 planning");
    });
  });

  it("006-FR-006 answers from the device when the fetch fails", async () => {
    // Seed the cache the way a previous online session would have left it,
    // then fail the request: this is the cold start on a train.
    await AsyncStorage.setItem(
      cacheKey(DEFAULT_SERVER_URL, "user-1"),
      JSON.stringify({
        projects: [{ id: "p-1", name: "Q3 planning" }],
        tags: [],
        fetchedAt: new Date().toISOString(),
      }),
    );

    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "GET /projects": () => {
        throw new TypeError("Network request failed");
      },
    });

    renderWithSession(<Projects />);

    await waitFor(() => expect(screen.getByTestId("names")).toHaveTextContent("Q3 planning"));
  });

  it("006-FR-006 surfaces the real failure when the device holds nothing", async () => {
    // An empty list here would read as "you have no projects", which is a
    // different and false statement from "we could not reach the server".
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "GET /projects": () => {
        throw new TypeError("Network request failed");
      },
    });

    renderWithSession(<Projects />);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("error"));
  });

  it("006-FR-006 caches and restores Tags on the same terms", async () => {
    await AsyncStorage.setItem(
      cacheKey(DEFAULT_SERVER_URL, "user-1"),
      JSON.stringify({
        projects: [],
        tags: [{ id: "t-1", name: "deep-work" }],
        fetchedAt: new Date().toISOString(),
      }),
    );

    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "GET /tags": () => {
        throw new TypeError("Network request failed");
      },
    });

    renderWithSession(<Tags />);

    await waitFor(() => expect(screen.getByTestId("names")).toHaveTextContent("deep-work"));
  });
});
