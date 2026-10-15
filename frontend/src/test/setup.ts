import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setAccessToken, setTokenRefresher } from "@/api/client";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  delete document.documentElement.dataset.theme;
  // The API client's token and refresher are module state, shared by every test in a file.
  setAccessToken(null);
  setTokenRefresher(null);
});
