import { useState } from "react";
import { Animated } from "react-native";

/**
 * A single `Animated.Value` that survives every re-render of a component.
 *
 * The React Native idiom for this is `useRef(new Animated.Value(x)).current`,
 * which reads a ref during render and so trips `react-hooks/refs`. The ref is
 * doing nothing a lazy `useState` initializer does not do better: the factory
 * runs once, the value is stable for the component's lifetime, and no ref is
 * read while rendering. The setter is deliberately dropped — the value is
 * mutated by the animation driver, never replaced.
 */
export function useAnimatedValue(initial: number): Animated.Value {
  const [value] = useState(() => new Animated.Value(initial));
  return value;
}
