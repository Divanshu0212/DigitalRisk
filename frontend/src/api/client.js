/**
 * Thin fetch wrapper used by all pages.
 *
 * - Base URL comes from NEXT_PUBLIC_API_BASE_URL (works on server + client).
 * - Every error is normalised into an { code, message, details } object so
 *   UI components can branch on error.code (REQUIREMENTS §11.2, §10.1).
 * - No external HTTP lib needed: Next.js polyfills fetch on the server, and
 *   the API only needs JSON + query strings.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(code, message, details = [], status = 0) {
    super(message);
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  let res;
  try {
    res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      // Next.js extends fetch with caching knobs; default to no-cache so the
      // leaderboard is always fresh on the client.
      cache: "no-store",
    });
  } catch (err) {
    // Network / DNS / CORS failure — surface a stable code to the UI.
    throw new ApiError(
      "NETWORK_ERROR",
      "Unable to reach the server. Check your connection or the API URL.",
      [],
      0
    );
  }

  const text = await res.text();
  const body = text ? safeJson(text) : null;

  if (!res.ok) {
    const errPayload = body?.error || {};
    throw new ApiError(
      errPayload.code || "UNKNOWN_ERROR",
      errPayload.message || `Request failed (${res.status})`,
      errPayload.details || [],
      res.status
    );
  }

  return body;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** POST /transaction (§4.1) */
export async function createTransaction(payload) {
  return request("/transaction", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** GET /users?search=&limit= */
export async function getUsers({ search = "", limit = 50 } = {}) {
  const qs = new URLSearchParams({ search, limit: String(limit) });
  return request(`/users?${qs.toString()}`);
}

/** GET /summary/{user_id} (§4.2) */
export async function getSummary(userId) {
  return request(`/summary/${encodeURIComponent(userId)}`);
}

/** GET /ranking?page=&limit= (§4.3) */
export async function getRanking({ page = 1, limit = 10 } = {}) {
  const qs = new URLSearchParams({ page: String(page), limit: String(limit) });
  return request(`/ranking?${qs.toString()}`);
}

/** GET /health */
export async function getHealth() {
  return request("/health");
}

export const API_BASE_URL = BASE_URL;
