import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";

import { colors } from "@/theme/tokens";

interface WaveformProps {
  /** Latest metering value in dBFS (about -160..0), if available. */
  metering?: number;
  active: boolean;
  bars?: number;
}

/** Sky bars driven by live mic metering — 4px bars per the design. */
export function Waveform({ metering, active, bars = 24 }: WaveformProps) {
  const [levels, setLevels] = useState<number[]>(() => Array(bars).fill(0.08));
  const meteringRef = useRef(metering);
  meteringRef.current = metering;

  useEffect(() => {
    if (!active) {
      setLevels(Array(bars).fill(0.08));
      return;
    }
    const timer = setInterval(() => {
      const db = meteringRef.current;
      // dBFS → 0..1 amplitude; -50 dB is treated as silence.
      const amplitude =
        typeof db === "number" ? Math.min(1, Math.max(0, (db + 50) / 50)) : 0.1;
      setLevels((previous) => [...previous.slice(1), Math.max(0.08, amplitude)]);
    }, 150);
    return () => clearInterval(timer);
  }, [active, bars]);

  return (
    <View style={styles.row}>
      {levels.map((level, index) => (
        <View key={index} style={[styles.bar, { height: 6 + level * 26 }]} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    height: 32,
  },
  bar: {
    width: 4,
    borderRadius: 2,
    backgroundColor: colors.brandPrimary,
  },
});
