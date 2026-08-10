import { useEffect } from "react";
import { BrowserRouter } from "react-router-dom";

import { setUnauthorizedHandler } from "./api/client";
import { AppRoutes } from "./app/AppRoutes";
import { useAuthStore } from "./stores/authStore";

export default function App(): React.JSX.Element {
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

  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
