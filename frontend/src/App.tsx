import { useEffect } from "react";
import { BrowserRouter } from "react-router-dom";

import { setAuthCausalityProvider, setUnauthorizedHandler } from "./api/client";
import { AppRoutes } from "./app/AppRoutes";
import { getAuthCausality, useAuthStore } from "./stores/authStore";

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
    setAuthCausalityProvider(getAuthCausality);
    return () => setAuthCausalityProvider(null);
  }, []);

  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
