/**
 * How every page's requests end: with the typed data, or with an `ApiRequestError` that carries the
 * API's own error code when it sent one, so React Query sees a rejection and a page can still say
 * what happened.
 */

import { failureMessage, readFailure, type Failure } from "./errors";

export class ApiRequestError extends Error {
  constructor(readonly failure: Failure) {
    super(failureMessage(failure));
    this.name = "ApiRequestError";
  }
}

/** The failure inside anything thrown by these requests. */
export function failureOf(error: unknown): Failure {
  if (error instanceof ApiRequestError) {
    return error.failure;
  }
  return { kind: "unreachable" };
}

interface Answer<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** The data, or the failure thrown. fetch throws when nothing answers; that becomes
 * "unreachable", unless the caller aborted, which is rethrown as it is. */
export async function answer<T>(request: Promise<Answer<T>>): Promise<T> {
  let result: Answer<T>;
  try {
    result = await request;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiRequestError({ kind: "unreachable" });
  }
  if (result.data === undefined) {
    throw new ApiRequestError(readFailure(result.response, result.error));
  }
  return result.data;
}
