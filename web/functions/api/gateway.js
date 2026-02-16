/**
 * CYORI REALTIME GATEWAY PROXY (Improved)
 * Relays WebSocket connections from Cloudflare to the VPS Bot
 */

const BOT_WS_URL = "ws://bkk.fe-grp.com:11050/api/gateway";

export async function onRequest(context) {
    const { request } = context;
    const upgradeHeader = request.headers.get("Upgrade");

    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
        return new Response("Expected Upgrade: websocket", { status: 426 });
    }

    try {
        // Standard Fetch Proxying for WebSockets
        // This is the most reliable way in Cloudflare Workers to proxy a WS handshake
        const response = await fetch(BOT_WS_URL, {
            headers: request.headers,
            method: request.method,
            // body: request.body // WS Handshake doesn't have body usually
        });

        // Ensure the response is passed through
        return response;
    } catch (err) {
        return new Response("Gateway Proxy Error: " + err.message, {
            status: 502,
            headers: { "Access-Control-Allow-Origin": "*" }
        });
    }
}
