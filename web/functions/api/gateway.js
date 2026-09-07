/**
 * Realtime gateway is intentionally disabled in the Community security hotfix.
 *
 * The legacy gateway accepted control frames before binding them to a verified
 * Discord identity. Dashboard clients automatically fall back to authenticated
 * HTTP polling/control until a token-bound WebSocket protocol is implemented.
 */
export async function onRequest() {
    return new Response(
        JSON.stringify({
            error: "realtime_temporarily_disabled",
            fallback: "authenticated_http",
        }),
        {
            status: 503,
            headers: {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
            },
        },
    );
}
