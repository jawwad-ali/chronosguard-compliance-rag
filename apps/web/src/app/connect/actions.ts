"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { backendUrl } from "@/lib/server/backend";
import { API_KEY_COOKIE, SESSION_MAX_AGE_SECONDS } from "@/lib/server/session";

export interface ConnectState {
  error: string | null;
}

/** Validate the org API key against the backend, then store it httpOnly. */
export async function connectAction(
  _previous: ConnectState,
  formData: FormData,
): Promise<ConnectState> {
  const apiKey = String(formData.get("apiKey") ?? "").trim();

  if (!apiKey.startsWith("cgk_") || !apiKey.includes(".")) {
    return { error: "That doesn't look like a ChronosGuard key (cgk_…)." };
  }

  let response: Response;
  try {
    response = await fetch(backendUrl("me"), {
      headers: { "X-API-Key": apiKey },
      cache: "no-store",
    });
  } catch {
    return { error: "Could not reach the ChronosGuard API. Is the backend running?" };
  }

  if (response.status === 401) {
    return { error: "Invalid or revoked API key." };
  }
  if (response.status === 403) {
    return { error: "This key lacks the read scope required for the dashboard." };
  }
  if (!response.ok) {
    return { error: `Unexpected response from the API (${response.status}).` };
  }

  const store = await cookies();
  store.set(API_KEY_COOKIE, apiKey, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: SESSION_MAX_AGE_SECONDS,
    path: "/",
  });

  redirect("/");
}

export async function disconnectAction(): Promise<void> {
  const store = await cookies();
  store.delete(API_KEY_COOKIE);
  redirect("/connect");
}
