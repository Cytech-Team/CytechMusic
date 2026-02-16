/**
 * CYORI REALTIME GATEWAY PROXY
 * Relays WebSocket connections from Cloudflare to the VPS Bot
 */

const BOT_WS_URL = "ws://bkk.fe-grp.com:11050/api/gateway";

export async function onRequest(context) {
    const upgradeHeader = context.request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
        return new Response("Expected Upgrade: websocket", { status: 426 });
    }

    try {
        // Forward the WebSocket request to the VPS
        const response = await fetch(BOT_WS_URL, {
            headers: context.request.headers,
        });

        if (response.status !== 101) {
            return new Response("Failed to upgrade to WebSocket", { status: 502 });
        }

        const serverWebSocket = response.webSocket;
        if (!serverWebSocket) {
            return new Response("VPS did not provide a WebSocket", { status: 502 });
        }

        const [client, server] = new WebSocketPair();
        server.accept();

        // Standard Relay Logic
        serverWebSocket.accept();

        // Pipe both ways
        server.addEventListener("message", (msg) => serverWebSocket.send(msg.data));
        serverWebSocket.addEventListener("message", (msg) => server.send(msg.data));

        server.addEventListener("close", () => serverWebSocket.close());
        serverWebSocket.addEventListener("close", () => server.close());

        server.addEventListener("error", () => serverWebSocket.close());
        serverWebSocket.addEventListener("error", () => server.close());

        return new Response(null, {
            status: 101,
            webSocket: client,
        });
    } catch (err) {
        return new Response("Gateway Offline: " + err.message, { status: 503 });
    }
}
