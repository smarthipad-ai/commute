// Cloudflare Worker that forwards RMV HAPI requests. RMV blocks GitHub's runners for hours at a time; Cloudflare's network
// gets through. Only GET requests to /hapi/... with the shared key in the x-relay-key header are forwarded, so it's not an open proxy.
// Setup: paste this into a Worker, add a secret named RELAY_KEY, deploy. See CLAUDE.md.
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (!env.RELAY_KEY || req.headers.get("x-relay-key") !== env.RELAY_KEY || req.method !== "GET" || !url.pathname.startsWith("/hapi/")) {
      return new Response("forbidden", { status: 403 });
    }
    const r = await fetch("https://www.rmv.de" + url.pathname + url.search, { headers: { accept: "application/json", "user-agent": "commute-relay" } });
    return new Response(r.body, { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json" } });
  },
};
