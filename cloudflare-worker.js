/**
 * Stream-Tools Cloudflare Worker
 *
 * Required bindings:
 * - KV namespace binding: STREAM_TOOLS_KV
 * - Worker secret: UPDATE_TOKEN
 *
 * Endpoints:
 * - POST /update           (auth required, JSON: { rank, streak })
 * - POST /update/rank      (auth required)
 * - POST /update/streak    (auth required)
 * - POST /update/session   (auth required, alias)
 * - GET  /rank
 * - GET  /streak
 * - GET  /session          (alias)
 * - GET  /health
 */

const KEY_RANK = "rank";
const KEY_SESSION = "session";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const route = `${request.method.toUpperCase()} ${url.pathname}`;

    // CORS preflight support
    if (request.method.toUpperCase() === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    try {
      switch (route) {
        case "POST /update":
          return await handleCombinedUpdate(request, env);

        case "POST /update/rank":
          return await handleUpdate(request, env, KEY_RANK);

        case "POST /update/streak":
          return await handleUpdate(request, env, KEY_SESSION);

        case "POST /update/session":
          return await handleUpdate(request, env, KEY_SESSION);

        case "GET /rank":
          return await handleRead(env, KEY_RANK);

        case "GET /streak":
          return await handleRead(env, KEY_SESSION);

        case "GET /session":
          return await handleRead(env, KEY_SESSION);

        case "GET /health":
          return jsonResponse({ ok: true }, 200);

        default:
          return textResponse("Not Found", 404);
      }
    } catch (err) {
      return jsonResponse(
        {
          ok: false,
          error: err instanceof Error ? err.message : "Unknown error",
        },
        500
      );
    }
  },
};

async function handleUpdate(request, env, key) {
  const token = request.headers.get("x-auth-token") || "";
  if (!env.UPDATE_TOKEN || token !== env.UPDATE_TOKEN) {
    return textResponse("Unauthorized", 401);
  }

  const text = (await request.text()).trim();
  if (!text) {
    return textResponse("Body is empty", 400);
  }

  await env.STREAM_TOOLS_KV.put(key, text);
  return textResponse("OK", 200);
}

async function handleCombinedUpdate(request, env) {
  const token = request.headers.get("x-auth-token") || "";
  if (!env.UPDATE_TOKEN || token !== env.UPDATE_TOKEN) {
    return textResponse("Unauthorized", 401);
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return textResponse("Invalid JSON body", 400);
  }

  const rank = typeof body.rank === "string" ? body.rank.trim() : "";
  const streak = typeof body.streak === "string" ? body.streak.trim() : "";

  if (!rank && !streak) {
    return textResponse("Body must include rank or streak", 400);
  }
  if (rank) {
    await env.STREAM_TOOLS_KV.put(KEY_RANK, rank);
  }
  if (streak) {
    await env.STREAM_TOOLS_KV.put(KEY_SESSION, streak);
  }
  return textResponse("OK", 200);
}

async function handleRead(env, key) {
  const value = (await env.STREAM_TOOLS_KV.get(key)) || "";
  return textResponse(value, 200);
}

function textResponse(text, status) {
  return new Response(text, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(),
    },
  });
}

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(),
    },
  });
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,x-auth-token",
  };
}
