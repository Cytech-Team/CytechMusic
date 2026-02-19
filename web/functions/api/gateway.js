/**
 * CYORI WEBSOCKET GATEWAY PROXY
 * Proxies WSS (from browser) → WS (to bot VPS)
 * Uses Cloudflare WebSocketPair API for proper bidirectional proxying.
 */

const BOT_WS_URL = "ws://bkk.fe-grp.com:11050/api/gateway";

export async function onRequest(context) {
    const { request } = context;

    // Only handle WebSocket upgrade requests
    const upgradeHeader = request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
        return new Response("Expected a WebSocket upgrade request", { status: 426 });
    }

    // Create a WebSocketPair: [client-facing, worker-facing]
    const [clientSocket, workerSocket] = Object.values(new WebSocketPair());

    // Handle the proxy in background (non-blocking)
    proxyWebSocket(workerSocket, request).catch((err) => {
        console.error("[Gateway] Proxy error:", err);
        try { workerSocket.close(1011, "Proxy error"); } catch (_) { }
    });

    // Return 101 Switching Protocols with the client-facing socket
    return new Response(null, {
        status: 101,
        webSocket: clientSocket,
    });
}

async function proxyWebSocket(workerSocket, request) {
    workerSocket.accept();

    // Connect to backend bot WS
    const backendResponse = await fetch(BOT_WS_URL, {
        headers: {
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Version": request.headers.get("Sec-WebSocket-Version") || "13",
            "Sec-WebSocket-Key": request.headers.get("Sec-WebSocket-Key") || "",
        },
    });

    const backendSocket = backendResponse.webSocket;
    if (!backendSocket) {
        workerSocket.close(1014, "Backend did not accept WebSocket");
        return;
    }

    backendSocket.accept();

    // Pipe: Client → Backend
    workerSocket.addEventListener("message", (event) => {
        try { backendSocket.send(event.data); } catch (_) { }
    });

    // Pipe: Backend → Client
    backendSocket.addEventListener("message", (event) => {
        try { workerSocket.send(event.data); } catch (_) { }
    });

    // Handle close from client
    workerSocket.addEventListener("close", (event) => {
        try { backendSocket.close(event.code || 1000, event.reason || ""); } catch (_) { }
    });

    // Handle close from backend
    backendSocket.addEventListener("close", (event) => {
        try { workerSocket.close(event.code || 1000, event.reason || ""); } catch (_) { }
    });

    // Handle errors
    workerSocket.addEventListener("error", () => {
        try { backendSocket.close(1011, "Client error"); } catch (_) { }
    });

    backendSocket.addEventListener("error", () => {
        try { workerSocket.close(1011, "Backend error"); } catch (_) { }
    });
}
