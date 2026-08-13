import { QueryClient } from "@tanstack/react-query";

import { bindRelaySession } from "./api/relaySession";

/** The application's sole process-global cache, bound to auth before React renders. */
export const queryClient = new QueryClient();

bindRelaySession(queryClient);
