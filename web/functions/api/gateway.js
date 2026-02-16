/**
 * CYORI REALTIME GATEWAY PROXY (Force Header)
 * Ensures 'Upgrade' header is explicitly sent to the VPS Bot
 */

const BOT_WS_URL = "http://bkk.fe-grp.com:11050/api/gateway";

export async function onRequest(context) {
    const { request } = context;

    // Explicitly reconstruct the request to ensure headers are preserved/set correctly
    // for a WebSocket upgrade over HTTP
    const init = {
        method: request.method,
        headers: new Headers(request.headers),
        // body: request.body // WS handshake has no body
    };

    // Force key headers if missing (though browser usually sends them)
    if (!init.headers.has("Upgrade")) init.headers.set("Upgrade", "websocket");
    if (!init.headers.has("Connection")) init.headers.set("Connection", "Upgrade");

    // Create a new Request object to avoid immutable properties of the original
    const newRequest = new Request(BOT_WS_URL, init);

    // Fetch from origin
    const response = await fetch(newRequest, {
        cf: {
            // Essential: Cloudflare specific flag to handle WebSocket upgrades
            cacheTtl: -1,
            polish: false,
            minify: { javascript: false, css: false, html: false }
        }
    });

    // If the response is a 101 Switching Protocols, we return it as is.
    // Cloudflare handles the underlying TCP connection upgrade.
    return response;
}
