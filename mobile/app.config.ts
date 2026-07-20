import type { ConfigContext, ExpoConfig } from "expo/config";

const apiOrigin = process.env.EXPO_PUBLIC_API_ORIGIN ?? "http://10.0.2.2:8000/api";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "Brain Buddy",
  slug: "brain-buddy",
  version: "1.0.0",
  scheme: "brainbuddy",
  orientation: "portrait",
  userInterfaceStyle: "light",
  ios: {
    bundleIdentifier: "com.brainbuddy.mobile",
    config: { usesNonExemptEncryption: false },
    infoPlist: {
      NSMicrophoneUsageDescription: "Brain Buddy uses your microphone only when you start a voice capture.",
    },
  },
  android: {
    package: "com.brainbuddy.mobile",
    permissions: ["android.permission.RECORD_AUDIO"],
  },
  plugins: [
    "expo-router",
    [
      "expo-secure-store",
      {
        configureAndroidBackup: true,
      },
    ],
  ],
  extra: {
    apiOrigin,
  },
});
