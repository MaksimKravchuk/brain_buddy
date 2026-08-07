import { Mic } from "lucide-react-native";
import { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";

import { colors, radii } from "@/theme/tokens";

interface PulsingMicProps {
  active: boolean;
  size?: number;
}

/**
 * The signature brain-dump mic: sky circle with an expanding ring
 * (scale 1→2 fade, 1.8s, ease-smooth). The product's only ambient motion
 * lives in the brain dump.
 */
export function PulsingMic({ active, size = 72 }: PulsingMicProps) {
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!active) {
      pulse.stopAnimation();
      pulse.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.timing(pulse, {
        toValue: 1,
        duration: 1800,
        easing: Easing.bezier(0.22, 1, 0.36, 1),
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [active, pulse]);

  const ringScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 2] });
  const ringOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] });

  return (
    <View style={{ width: size * 2, height: size * 2, alignItems: "center", justifyContent: "center" }}>
      {active ? (
        <Animated.View
          style={[
            styles.ring,
            {
              width: size,
              height: size,
              borderRadius: radii.full,
              transform: [{ scale: ringScale }],
              opacity: ringOpacity,
            },
          ]}
        />
      ) : null}
      <View
        style={[
          styles.button,
          { width: size, height: size, borderRadius: radii.full },
        ]}
      >
        <Mic size={size * 0.42} color="#FFFFFF" strokeWidth={2} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  ring: {
    position: "absolute",
    backgroundColor: "rgba(14, 165, 233, 0.16)",
  },
  button: {
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
});
