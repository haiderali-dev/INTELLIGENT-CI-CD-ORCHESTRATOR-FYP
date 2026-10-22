/**
 * Where to go after signing in. The page asked for travels in `?next=`, which anyone can write
 * into a link, so only a path on this site is followed. Anything else, such as
 * `//elsewhere.example` or `https://elsewhere.example`, would make the sign-in page a redirect
 * to another site, and goes to the overview instead.
 */

export const SIGN_IN_PATH = "/sign-in";
const HOME = "/";

export function safeNext(raw: string | null): string {
  if (!raw?.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return HOME;
  }
  // Resolved against a placeholder origin: if the result leaves it, the path was not local.
  const base = "http://app.invalid";
  let url: URL;
  try {
    url = new URL(raw, base);
  } catch {
    return HOME;
  }
  if (url.origin !== base || url.pathname === SIGN_IN_PATH) {
    return HOME;
  }
  // Resolving can itself make a protocol-relative path: "/.//evil.example" resolves to
  // "//evil.example", which a browser reads as another site. The router collapses "//" today, but
  // this function must not lean on that (independent security review, finding 8).
  if (url.pathname.startsWith("//") || url.pathname.startsWith("/\\")) {
    return HOME;
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The sign-in page, carrying the page to return to unless that is the overview. */
export function signInPath(next: string | null): string {
  const target = next === null ? HOME : safeNext(next);
  return target === HOME ? SIGN_IN_PATH : `${SIGN_IN_PATH}?next=${encodeURIComponent(target)}`;
}
