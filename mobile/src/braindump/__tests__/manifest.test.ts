import { chunkSha256Hex, manifestHash } from "../manifest";

// Golden vectors precomputed with Python's hashlib/json to pin the
// byte-exact contract with the backend's _brain_dump_manifest_hash
// (json.dumps(..., sort_keys=True, separators=(",", ":"))).

const A64 = "a".repeat(64);
const B64 = "b".repeat(64);

describe("chunkSha256Hex", () => {
  it("hashes raw bytes to lowercase hex", () => {
    const bytes = new TextEncoder().encode("hello");
    expect(chunkSha256Hex(bytes)).toBe(
      "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    );
  });

  it("hashes the empty input", () => {
    expect(chunkSha256Hex(new Uint8Array(0))).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });
});

describe("manifestHash", () => {
  it("matches the backend for a single chunk", () => {
    const hash = manifestHash([{ chunk_number: 0, sha256: A64, size_bytes: 3 }], 1);
    expect(hash).toBe("cf6404ceb68ddd42b93d089d6e9fe8cb3efe25608755b5244b23138fd3980f2a");
  });

  it("sorts out-of-order chunks and drops chunks beyond expected_chunks", () => {
    const hash = manifestHash(
      [
        { chunk_number: 1, sha256: B64, size_bytes: 12345 },
        { chunk_number: 2, sha256: "c".repeat(64), size_bytes: 1 },
        { chunk_number: 0, sha256: A64, size_bytes: 917504 },
      ],
      2,
    );
    expect(hash).toBe("fa8554277680a980a77af253118c8c6de90fe50760997796ee78bdfce0d51d6c");
  });

  it("ignores extra metadata keys on input objects", () => {
    const chunk = { chunk_number: 0, sha256: A64, size_bytes: 3, uploaded_at: "x" };
    expect(manifestHash([chunk], 1)).toBe(
      "cf6404ceb68ddd42b93d089d6e9fe8cb3efe25608755b5244b23138fd3980f2a",
    );
  });

  it("does not mutate the caller's array order", () => {
    const chunks = [
      { chunk_number: 1, sha256: B64, size_bytes: 2 },
      { chunk_number: 0, sha256: A64, size_bytes: 1 },
    ];
    manifestHash(chunks, 2);
    expect(chunks[0].chunk_number).toBe(1);
  });
});
