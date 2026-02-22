import { useEffect, useState } from "react";

export function useDelayedUnmount(isOpen: boolean, durationMs: number = 200) {
  const [shouldRender, setShouldRender] = useState(isOpen);

  useEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      return;
    }
    const timer = window.setTimeout(() => setShouldRender(false), durationMs);
    return () => clearTimeout(timer);
  }, [isOpen, durationMs]);

  return {
    shouldRender: isOpen || shouldRender,
    isAnimatingOut: !isOpen && shouldRender,
  };
}
