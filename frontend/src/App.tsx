import { useEffect } from "react";
import { BrowserRouter } from "react-router-dom";

import { setAuthEpochProvider, setUnauthorizedHandler } from "./api/client";
import { AppRoutes } from "./app/AppRoutes";
import { getAuthEpoch, useAuthStore } from "./stores/authStore";

export default function App(): JSX.Element {
  const hydrate = useAuthStore((state) => state.hydrate);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  useEffect(() => {
    setAuthEpochProvider(getAuthEpoch);
    return () => setAuthEpochProvider(null);
  }, []);

  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
