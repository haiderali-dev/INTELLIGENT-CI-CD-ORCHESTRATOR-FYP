/**
 * What went wrong with a request. There are three ways:
 * - the API answered with its one error shape (D-055), whose code a page can switch on;
 * - nothing answered: the request threw, or whatever sits in front of the API answered for it;
 * - something answered that is not the API, such as a static server's 404 page.
 */

import type { ApiErrorBody } from "./client";

export type Failure =
  | { kind: "api"; status: number; error: ApiErrorBody }
  | { kind: "unreachable" }
  | { kind: "unexpected"; status: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The error shape, checked at run time. openapi-fetch types an error body from the schema, but it
 * parses whatever arrived, and a proxy's error page is not the schema.
 */
export function isApiErrorResponse(value: unknown): value is { error: ApiErrorBody } {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false;
  }
  return typeof value.error.code === "string" && typeof value.error.message === "string";
}

/** Reads a failed response and the body openapi-fetch parsed from it. */
export function readFailure(response: Response, body: unknown): Failure {
  if (isApiErrorResponse(body)) {
    const { code, message, details } = body.error;
    return {
      kind: "api",
      status: response.status,
      error: { code, message, details: isRecord(details) ? details : {} },
    };
  }
  // The backend sends its own shape even for a crash, so a 5xx without it came from in front of
  // the backend: the dev server's proxy, or a gateway, saying nothing answered behind it.
  if (response.status >= 500) {
    return { kind: "unreachable" };
  }
  return { kind: "unexpected", status: response.status };
}

/** How long a RATE_LIMITED answer asks the caller to wait, if it says. */
export function retryAfterSeconds(failure: Failure): number | null {
  if (failure.kind !== "api" || failure.error.code !== "RATE_LIMITED") {
    return null;
  }
  const seconds = failure.error.details.retry_after_seconds;
  return typeof seconds === "number" && seconds > 0 ? Math.ceil(seconds) : null;
}

export const UNREACHABLE_MESSAGE =
  "The server did not answer. Check that the backend is running, then try again.";

/** One sentence for any failure: the API's own message, or what happened and what to do. */
export function failureMessage(failure: Failure): string {
  switch (failure.kind) {
    case "api":
      return failure.error.message;
    case "unreachable":
      return UNREACHABLE_MESSAGE;
    case "unexpected":
      return `The server sent an answer this page cannot read (HTTP ${failure.status}). Try again, and if it happens again, check the backend log.`;
  }
}
