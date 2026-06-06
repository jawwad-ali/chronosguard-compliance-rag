import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/** httpOnly cookie holding the org API key — client JS can never read it. */
export const API_KEY_COOKIE = "cg_api_key";

export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

export const getApiKey = async (): Promise<string | null> => {
  const store = await cookies();
  return store.get(API_KEY_COOKIE)?.value ?? null;
};

/** Server-component guard for the authenticated app shell. */
export const requireApiKey = async (): Promise<string> => {
  const key = await getApiKey();
  if (!key) redirect("/connect");
  return key;
};
