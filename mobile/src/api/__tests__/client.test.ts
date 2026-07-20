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
