import { useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, StyleSheet, TextInput, View } from "react-native";

import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { Screen } from "@/components/Screen";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

export default function SettingsScreen() {
  const router = useRouter();
  const { me, serverUrl, updateServerUrl, signOut, voiceEnabled } = useSession();
  const [serverDraft, setServerDraft] = useState(serverUrl);
  const [saved, setSaved] = useState(false);

  const saveServer = async () => {
    await updateServerUrl(serverDraft);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <Screen padTop padBottom>
      <ScrollView contentContainerStyle={styles.scroll}>
        <BBText variant="title">Settings</BBText>

        <BBText variant="label">Account</BBText>
        <View style={styles.card}>
          <BBText variant="body" weight="medium" color={colors.fg1}>
            {me?.email ?? "Not signed in"}
          </BBText>
          <BBText variant="caption" color={colors.fg5}>
            {voiceEnabled
              ? "Voice brain dump is enabled for this account."
              : "Voice brain dump is not enabled for this account."}
          </BBText>
        </View>

        <BBText variant="label">Server</BBText>
        <View style={styles.card}>
          <TextInput
            style={styles.input}
            value={serverDraft}
            onChangeText={setServerDraft}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder={DEFAULT_SERVER_URL}
            placeholderTextColor={colors.fg6}
          />
          <BBText variant="caption" color={colors.fg5}>
            Changing the server signs you out of the current one.
          </BBText>
          <Button variant="secondary" onPress={saveServer}>
            {saved ? "Saved" : "Save server URL"}
          </Button>
        </View>

        <Button
          variant="destructive"
          onPress={async () => {
            await signOut();
            router.back();
          }}
        >
          Sign out
        </Button>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  scroll: {
    padding: space.s5,
    gap: space.s3,
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s3,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: 44,
  },
});
