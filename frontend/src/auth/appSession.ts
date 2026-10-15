import { api, setTokenRefresher } from "@/api/client";

import { browserSessionStorage, Session } from "./session";

/** The app's one session. A request that comes back 401 is repeated once after its refresh. */
export const session = new Session({ client: api, storage: browserSessionStorage() });

setTokenRefresher(() => session.refresh());
