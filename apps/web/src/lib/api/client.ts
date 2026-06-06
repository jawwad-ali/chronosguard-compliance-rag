import type { ProblemDetail } from "@/lib/api/types";

/** Single error shape end-to-end: the API's RFC 9457 problem+json. */
export class ApiError extends Error {
  readonly problem: ProblemDetail;

  constructor(problem: ProblemDetail) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }
}

const FALLBACK_PROBLEM = (status: number): ProblemDetail => ({
  type: "about:blank",
  title: "Unexpected error",
  status,
  request_id: "-",
});

/**
 * Browser-side fetch against the same-origin proxy (/api/cg/*).
 * Throws ApiError on any non-2xx; callers always get typed JSON.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/cg/${path.replace(/^\/+/, "")}`, {
    ...init,
    headers: {
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (response.status === 204) return undefined as T;

  const isJson = response.headers
    .get("content-type")
    ?.includes("json");

  if (!response.ok) {
    const problem: ProblemDetail = isJson
      ? await response.json().catch(() => FALLBACK_PROBLEM(response.status))
      : FALLBACK_PROBLEM(response.status);
    throw new ApiError(problem);
  }

  return (await response.json()) as T;
}

export const pageQuery = (limit: number, offset: number): string =>
  `?limit=${limit}&offset=${offset}`;
