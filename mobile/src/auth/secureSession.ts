import * as SecureStore from "expo-secure-store";

const SESSION_KEY = "brainbuddy.mobile.session";
const SERVICE = "com.brainbuddy.mobile.session";

export async function readSessionToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SESSION_KEY, { keychainService: SERVICE });
}

export async function saveSessionToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(SESSION_KEY, token, {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    keychainService: SERVICE,
  });
}

export async function clearSessionToken(): Promise<void> {
  await SecureStore.deleteItemAsync(SESSION_KEY, { keychainService: SERVICE });
}
