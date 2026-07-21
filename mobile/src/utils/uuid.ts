import * as Crypto from "expo-crypto";

/**
 * Expo's native-backed UUID v4 primitive. `globalThis.crypto.randomUUID` is
 * not guaranteed to exist on the Hermes engine that ships with Android/iOS,
 * so command-identity keys must come from `expo-crypto` instead of the
 * browser/Node `crypto` global.
 */
export function randomUUID(): string {
  return Crypto.randomUUID();
}
