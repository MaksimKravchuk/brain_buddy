import * as Crypto from "expo-crypto";

import { uuidNumber } from "@/test/expoCryptoMock";

import { newIdempotencyKey } from "../ids";

describe("newIdempotencyKey", () => {
  it("returns the platform UUID, so two attempts are never confused", () => {
    expect(newIdempotencyKey()).toBe(uuidNumber(1));
    expect(newIdempotencyKey()).toBe(uuidNumber(2));
  });

  it("delegates to the crypto module rather than rolling its own randomness", () => {
    const randomUUID = jest.spyOn(Crypto, "randomUUID").mockReturnValue("fixed-uuid" as never);
    try {
      expect(newIdempotencyKey()).toBe("fixed-uuid");
    } finally {
      randomUUID.mockRestore();
    }
  });
});
