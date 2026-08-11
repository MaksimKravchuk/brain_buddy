import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";

import {
  advanceLevels,
  amplitudeFromMetering,
  idleLevels,
  WAVEFORM_TICK_MS,
} from "@/braindump/waveform";
import { colors } from "@/theme/tokens";

interface WaveformProps {
  /** Latest metering value in dBFS (about -160..0), if available. */
  metering?: number;
  active: boolean;
  bars?: number;
}

/** Sky bars driven by live mic metering — 4px bars per the design. */
export function Waveform({ metering, active, bars = 24 }: WaveformProps) {
  // Mounting the live bars only while recording is what resets the rolling
  // buffer between sessions: a new recording gets a new component instance and
  // therefore starts from silence, with no state to clear.
  return active ? (
    <LiveBars key={bars} metering={metering} bars={bars} />
  ) : (
    <Bars levels={idleLevels(bars)} />
  );
}

function LiveBars({ metering, bars }: { metering?: number; bars: number }) {
  const [levels, setLevels] = useState<number[]>(() => idleLevels(bars));

  // The interval reads the newest metering without re-subscribing on every
  // reading, so the ref is written from an effect rather than during render.
  const meteringRef = useRef(metering);
  useEffect(() => {
    meteringRef.current = metering;
  }, [metering]);

  useEffect(() => {
    const timer = setInterval(() => {
      const amplitude = amplitudeFromMetering(meteringRef.current);
      setLevels((previous) => advanceLevels(previous, amplitude));
    }, WAVEFORM_TICK_MS);
    return () => {
      clearInterval(timer);
    };
  }, []);

  return <Bars levels={levels} />;
}

function Bars({ levels }: { levels: readonly number[] }) {
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
