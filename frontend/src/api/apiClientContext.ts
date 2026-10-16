import { createContext, useContext, useMemo } from "react";

import { api, type ApiClient } from "./client";

/**
 * The HTTP client every page's requests go through. The app uses the real one; a test supplies one
 * over a fake backend (src/test/renderRoutes.tsx), and every page's requests follow it.
 */
export const ApiClientContext = createContext<ApiClient>(api);

/** A page's requests, built from a module's factory over the client in context. */
export function useApi<T>(factory: (client: ApiClient) => T): T {
  const client = useContext(ApiClientContext);
  return useMemo(() => factory(client), [client, factory]);
}
