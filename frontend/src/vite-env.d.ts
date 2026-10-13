/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The backend's origin, for a build served apart from it (Compose's frontend profile). Unset,
   * the app calls /api and /ws on its own origin, which the dev server proxies. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
