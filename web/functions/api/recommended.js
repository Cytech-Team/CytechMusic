/**
 * CYORI RECOMMENDED API PROXY
 * Direct Entry Point for Recommended Tracks
 */
const VPS_API = "http://bkk.fe-grp.com:11050/api/recommended";

export async function onRequest(context) {
    const { request } = context;
    const url = new URL(request.url);

    // Construct target URL with same query params
    const targetUrl = new URL(VPS_API);
    url.searchParams.forEach((v, k) => {
        targetUrl.searchParams.set(k, v);
    });

    try {
        const response = await fetch(targetUrl.toString(), {
            method: "GET",
            headers: { "Content-Type": "application/json" }
        });

        const data = await response.text();

        return new Response(data, {
            status: response.status,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            }
        });
    } catch (err) {
        return new Response(JSON.stringify({ status: "error", message: "VPS Offline" }), {
            status: 502,
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    }
}
