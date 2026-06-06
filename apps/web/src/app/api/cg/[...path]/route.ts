import { type NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/server/backend";
import { getApiKey } from "@/lib/server/session";

/**
 * Same-origin proxy to the ChronosGuard API.
 *
 * The org API key lives in an httpOnly cookie and is attached here, server
 * side — browser code never holds the credential, and CORS never enters the
 * picture. Backend errors (RFC 9457 problem+json) pass through verbatim so
 * the client error handling stays single-shape.
 */

const PROXIED_METHODS = ["GET", "POST", "PATCH", "DELETE"] as const;

const unauthorized = (): NextResponse =>
  NextResponse.json(
    {
      type: "about:blank",
      title: "Not connected",
      status: 401,
      detail: "No API key session. Connect your organization first.",
      request_id: "-",
    },
    { status: 401, headers: { "content-type": "application/problem+json" } },
  );

const upstreamUnreachable = (): NextResponse =>
  NextResponse.json(
    {
      type: "about:blank",
      title: "API unreachable",
      status: 502,
      detail: "Could not reach the ChronosGuard API. Is the backend running?",
      request_id: "-",
    },
    { status: 502, headers: { "content-type": "application/problem+json" } },
  );

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const apiKey = await getApiKey();
  if (!apiKey) return unauthorized();

  const { path } = await context.params;
  const search = request.nextUrl.search;
  const target = backendUrl(path.join("/")) + search;

  const headers = new Headers({ "X-API-Key": apiKey });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: PROXIED_METHODS.includes(
        request.method as (typeof PROXIED_METHODS)[number],
      ) && request.method !== "GET"
        ? await request.arrayBuffer()
        : undefined,
      cache: "no-store",
    });
  } catch {
    return upstreamUnreachable();
  }

  const responseHeaders = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("content-type", upstreamType);
  const requestId = upstream.headers.get("x-request-id");
  if (requestId) responseHeaders.set("x-request-id", requestId);

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
