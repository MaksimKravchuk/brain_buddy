import * as FileSystem from "expo-file-system/legacy";

import { clearSessionToken } from "./secureSession";

const markerPath = `${FileSystem.documentDirectory}brainbuddy-install-marker`;

/** Clears Keychain residue if this app-document installation marker is absent. */
export async function establishInstallMarker(): Promise<void> {
  const marker = await FileSystem.getInfoAsync(markerPath);
  if (!marker.exists) {
    await clearSessionToken();
    await FileSystem.writeAsStringAsync(markerPath, "installed");
  }
}
