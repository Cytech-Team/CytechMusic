/**
 * CYORI CLOUDFLARE PAGES PROXY
 * =============================
 * Routes all dashboard requests to the VPS bot API.
 *
 * Flow:
 *   Browser → /api/proxy (Cloudflare)  →  VPS /api/proxy  →  Bot
 *   Browser ← response                 ←  VPS response    ←  Bot
 *
 * Special cases handled IN this file (not forwarded):
 *   - Stripe checkout  (needs STRIPE_SECRET_KEY env var)
 *   - GitHub / Stripe webhooks
 *   - register_bot / poll  (stubs)
 */

const VPS_API = "http://bkk.fe-grp.com:11050";
const SUCCESS_URL = "https://cyori.pages.dev/success.html";

const PLANS = {
    "1_month": { price: 2900, name: "Premium (1 Month)" },
    "3_months": { price: 7900, name: "Premium (3 Months)" },
    "6_months": { price: 14900, name: "Premium (6 Months)" },
    "1_year": { price: 28900, name: "Premium (1 Year)" },
    "lifetime": { price: 78900, name: "Premium (Lifetime)" },
};

const CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
}

export async function onRequest(context) {
    const { request, env } = context;
    const url = new URL(request.url);
    const method = request.method;

    // ── 0. CORS Preflight ─────────────────────────────────────────────────
    if (method === "OPTIONS") {
        return new Response(null, { headers: CORS_HEADERS });
    }

    // ── 1. Read body (once, prevents "Body already consumed") ───────────────
    let bodyText = "";
    let bodyData = null;
    if (method === "POST") {
        try {
            bodyText = await request.text();
            bodyData = JSON.parse(bodyText);
        } catch (e) { /* empty or non-JSON body */ }
    }

    const action = url.searchParams.get("action") || (bodyData && bodyData.action);

    // ── 2. Stripe Checkout ────────────────────────────────────────────────
    if (action === "create_checkout") {
        const stripeKey = env.STRIPE_SECRET_KEY;
        if (!stripeKey) {
            return jsonResponse({ status: "error", message: "Stripe key missing" }, 500);
        }
        const { user_id, plan_id } = bodyData || {};
        const plan = PLANS[plan_id];
        if (!plan) return jsonResponse({ status: "error", message: "Invalid plan" }, 400);

        try {
            const stripeParams = new URLSearchParams({
                "ui_mode": "embedded",
                "return_url": `${SUCCESS_URL}?session_id={CHECKOUT_SESSION_ID}`,
                "mode": "payment",
                "payment_method_types[0]": "card",
                "payment_method_types[1]": "promptpay",
                "line_items[0][price_data][currency]": "thb",
                "line_items[0][price_data][product_data][name]": plan.name,
                "line_items[0][price_data][unit_amount]": plan.price.toString(),
                "line_items[0][quantity]": "1",
                "metadata[user_id]": String(user_id),
                "metadata[plan_id]": plan_id,
                "metadata[days]": String(getDaysFromPlan(plan_id)),
            });
            const stripeRes = await fetch("https://api.stripe.com/v1/checkout/sessions", {
                method: "POST",
                headers: { Authorization: `Bearer ${stripeKey}`, "Content-Type": "application/x-www-form-urlencoded" },
                body: stripeParams.toString(),
            });
            const session = await stripeRes.json();
            if (session.error) throw new Error(session.error.message);
            return jsonResponse({ status: "success", clientSecret: session.client_secret });
        } catch (err) {
            return jsonResponse({ status: "error", message: "Stripe: " + err.message }, 500);
        }
    }

    // ── 3. Webhooks (GitHub / Stripe) ────────────────────────────────────
    const isGithub = request.headers.get("x-github-event");
    const isStripe = request.headers.get("stripe-signature");
    if (isGithub || isStripe) {
        const target = isGithub
            ? `${VPS_API}/api/webhook/github`
            : `${VPS_API}/stripe/webhook`;
        try {
            await fetch(target, {
                method: "POST",
                headers: { "Content-Type": request.headers.get("Content-Type") || "application/json" },
                body: bodyText,
            });
            return new Response("OK", { status: 200 });
        } catch (e) {
            return new Response("Broadcast Failed", { status: 502 });
        }
    }

    // ── 4. register_bot / poll  (stubs — Cloudflare is static) ──────────
    if (action === "register_bot") {
        return jsonResponse({ status: "success", info: "Cloudflare proxy – static" });
    }
    if (action === "poll") {
        return jsonResponse([]);
    }

    // ── 5. Forward everything else → VPS /api/proxy ──────────────────────
    //    The VPS handles all action routing internally.
    const targetUrl = new URL(`${VPS_API}/api/proxy`);
    // Preserve query params (e.g. ?action=status&guild_id=xxx on GET requests)
    url.searchParams.forEach((v, k) => targetUrl.searchParams.set(k, v));

    try {
        const vpsRes = await fetch(targetUrl.toString(), {
            method,
            headers: { "Content-Type": "application/json" },
            body: (method === "POST" || method === "PUT") ? bodyText : null,
        });
        const respText = await vpsRes.text();
        return new Response(respText, {
            status: vpsRes.status,
            headers: { "Content-Type": "application/json", ...CORS_HEADERS },
        });
    } catch (err) {
        return jsonResponse({ error: "VPS Offline or unreachable" }, 502);
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────
function getDaysFromPlan(planId) {
    const map = { "1_month": 30, "3_months": 90, "6_months": 180, "1_year": 365, "lifetime": 36500 };
    return map[planId] ?? 0;
}
