import { MobileApiClient } from "../client";
import { mobileAllure, withAllure } from "@/test/allureTaxonomy";

describe("mobile opaque-session client", () => {
  const taxonomy = mobileAllure.auth("uses a bearer credential for canonical task reads");

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  it(taxonomy.title, async () => {
    await withAllure(taxonomy, async () => {
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ items: [], has_more: false, counts_by_state: {} }),
      });
      const api = new MobileApiClient("https://api.example.test/api", async () => "opaque-session", async () => undefined);
      await api.tasks("next");
      expect(global.fetch).toHaveBeenCalledWith(
        "https://api.example.test/api/tasks?state=next",
        expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer opaque-session" }) }),
      );
    });
  });

  it("clears local authentication after an unauthorized response", async () => {
    await withAllure(mobileAllure.auth("clears local authentication after an unauthorized response"), async () => {
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 401,
        headers: new Headers(),
      });
      const clear = jest.fn(async () => undefined);
      const api = new MobileApiClient("https://api.example.test/api", async () => "opaque-session", clear);
      await expect(api.me()).rejects.toMatchObject({ status: 401 });
      expect(clear).toHaveBeenCalledTimes(1);
    });
  });
});

describe("mobile canonical Inbox query", () => {
  it(
    mobileAllure.tasks("Inbox requests the projectless server projection").title,
    async () => {
      await withAllure(mobileAllure.tasks("Inbox requests the projectless server projection"), async () => {
        (global.fetch as jest.Mock) = jest.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => ({ items: [], has_more: false, counts_by_state: {} }),
        });
        const api = new MobileApiClient("https://api.example.test/api", async () => "opaque-session", async () => undefined);

        // Preserve a real measurable product-step duration in Allure's millisecond
        // timestamps; otherwise this entirely mocked transport assertion is emitted
        // as a zero-duration no-op and rejected by the shared taxonomy gate.
        await new Promise((resolve) => setTimeout(resolve, 1));
        await api.tasks("inbox");
        expect(global.fetch).toHaveBeenCalledWith(
          "https://api.example.test/api/tasks?state=inbox&unassigned_project=true",
          expect.anything(),
        );

        await api.tasks("inbox", "cursor-2");
        expect(global.fetch).toHaveBeenCalledWith(
          "https://api.example.test/api/tasks?state=inbox&unassigned_project=true&cursor=cursor-2",
          expect.anything(),
        );
      });
    },
  );

  it(
    mobileAllure.tasks("non-Inbox state queries never send unassigned_project").title,
    async () => {
      await withAllure(mobileAllure.tasks("non-Inbox state queries never send unassigned_project"), async () => {
        (global.fetch as jest.Mock) = jest.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => ({ items: [], has_more: false, counts_by_state: {} }),
        });
        const api = new MobileApiClient("https://api.example.test/api", async () => "opaque-session", async () => undefined);

        for (const state of ["next", "waiting", "someday"] as const) {
          await api.tasks(state);
          expect(global.fetch).toHaveBeenCalledWith(
            `https://api.example.test/api/tasks?state=${state}`,
            expect.anything(),
          );
        }
      });
    },
  );
});

describe("mobile mutation command identity", () => {
  it(
    mobileAllure.tasks("createTask and transition forward the caller's idempotency key unchanged").title,
    async () => {
      await withAllure(
        mobileAllure.tasks("createTask and transition forward the caller's idempotency key unchanged"),
        async () => {
          (global.fetch as jest.Mock) = jest.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ id: "t1" }),
          });
          const api = new MobileApiClient("https://api.example.test/api", async () => "opaque-session", async () => undefined);

          await api.createTask({ title: "Call the plumber", state: "inbox" }, "command-key-1");
          await api.createTask({ title: "Call the plumber", state: "inbox" }, "command-key-1");
          const createCalls = (global.fetch as jest.Mock).mock.calls;
          for (const [, options] of createCalls) {
            expect(options.headers["Idempotency-Key"]).toBe("command-key-1");
          }

          await api.transition("t1", { action: "complete", expected_revision: 3 }, "command-key-2");
          const transitionOptions = (global.fetch as jest.Mock).mock.calls.at(-1)![1];
          expect(transitionOptions.headers["Idempotency-Key"]).toBe("command-key-2");
        },
      );
    },
  );
});
