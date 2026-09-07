/**
 * Recommended tracks proxy for Community deployments.
 * No Cyori/Cytech production backend is used by default.
 */
export async function onRequest(context) {
    const { request, env } = context;
    const backend = (env.VPS_API_URL || env.BOT_API_URL || "").replace(/\/+$/, "");
    if (!backend) {
        return new Response(JSON.stringify({ error: "backend_not_configured" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
        });
    }

    const sourceUrl = new URL(request.url);
    const targetUrl = new URL(`${backend}/api/proxy`);
    targetUrl.searchParams.set("action", "recommended");
    sourceUrl.searchParams.forEach((value, key) => {
        if (key !== "action") targetUrl.searchParams.set(key, value);
    });

    try {
        const response = await fetch(targetUrl.toString(), {
            method: "GET",
            headers: { "Content-Type": "application/json" },
        });
        return new Response(await response.text(), {
            status: response.status,
            headers: {
                "Content-Type": response.headers.get("Content-Type") || "application/json",
                "Access-Control-Allow-Origin": env.DASHBOARD_ORIGIN || sourceUrl.origin,
                "Vary": "Origin",
            },
        });
    } catch (_) {
        return new Response(JSON.stringify({ error: "backend_unreachable" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
}
