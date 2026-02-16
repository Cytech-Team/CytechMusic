/**
 * CYORI ULTIMATE INNER RUNNER
 * Handles Proxying, Payments (Stripe), and Webhook Broadcasting
 */
const VPS_API = "http://bkk.fe-grp.com:11050";
const SUCCESS_URL = "https://cyori.pages.dev/success.html";

const PLANS = {
    "1_month": { price: 2900, name: "Premium (1 Month)" },
    "3_months": { price: 7900, name: "Premium (3 Months)" },
    "6_months": { price: 14900, name: "Premium (6 Months)" },
    "1_year": { price: 28900, name: "Premium (1 Year)" },
    "lifetime": { price: 78900, name: "Premium (Lifetime)" }
};

export async function onRequest(context) {
    const { request, env } = context;
    const url = new URL(request.url);
    const method = request.method;

    // 1. Handle CORS Preflight
    if (method === "OPTIONS") {
        return new Response(null, {
            headers: {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        });
    }

    // 2. Read body once (Prevent "Body already consumed" error)
    let bodyText = "";
    let bodyData = null;
    if (method === "POST") {
        try {
            bodyText = await request.text();
            bodyData = JSON.parse(bodyText);
        } catch (e) { /* Not JSON or empty */ }
    }

    const action = url.searchParams.get("action") || (bodyData && bodyData.action);

    // --- CASE A: STRIPE CHECKOUT ---
    if (action === "create_checkout") {
        const stripeKey = env.STRIPE_SECRET_KEY;
        if (!stripeKey) {
            return new Response(JSON.stringify({
                status: "error",
                message: "Stripe Key missing! Go to Settings -> Functions -> Variables and add STRIPE_SECRET_KEY"
            }), { status: 500, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" } });
        }

        const { user_id, plan_id } = bodyData || {};
        const plan = PLANS[plan_id];
        if (!plan) return new Response(JSON.stringify({ status: "error", message: "Invalid Plan ID" }), { status: 400, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" } });

        try {
            const stripeParams = new URLSearchParams({
                "ui_mode": "embedded",
                "return_url": SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
                "mode": "payment",
                "payment_method_types[0]": "card",
                "payment_method_types[1]": "promptpay",
                "line_items[0][price_data][currency]": "thb",
                "line_items[0][price_data][product_data][name]": plan.name,
                "line_items[0][price_data][unit_amount]": plan.price.toString(),
                "line_items[0][quantity]": "1",
                "metadata[user_id]": user_id.toString(),
                "metadata[plan_id]": plan_id,
                "metadata[days]": getDaysFromPlan(plan_id).toString()
            });

            const stripeRes = await fetch("https://api.stripe.com/v1/checkout/sessions", {
                method: "POST",
                headers: { "Authorization": `Bearer ${stripeKey}`, "Content-Type": "application/x-www-form-urlencoded" },
                body: stripeParams.toString()
            });
            const session = await stripeRes.json();

            if (session.error) throw new Error(session.error.message);

            return new Response(JSON.stringify({ status: "success", clientSecret: session.client_secret }), {
                headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
            });
        } catch (err) {
            return new Response(JSON.stringify({ status: "error", message: "Stripe API: " + err.message }), {
                status: 500, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
            });
        }
    }

    // --- CASE B: WEBHOOKS ---
    const isGithub = request.headers.get("x-github-event");
    const isStripe = request.headers.get("stripe-signature");

    if (isGithub || isStripe) {
        const targetWebhook = isGithub ? `${VPS_API}/api/webhook/github` : `${VPS_API}/stripe/webhook`;
        try {
            await fetch(targetWebhook, {
                method: "POST",
                headers: { "Content-Type": request.headers.get("Content-Type") || "application/json" },
                body: bodyText
            });
            return new Response("OK", { status: 200 });
        } catch (e) {
            return new Response("Broadcast Failed", { status: 502 });
        }
    }

    // --- CASE C: DYNAMIC BOT REGISTRATION & POLLING ---
    if (action === "register_bot") {
        return new Response(JSON.stringify({ status: "success", info: "Cloudflare Proxy is currently static" }), {
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    }

    if (action === "poll") {
        return new Response(JSON.stringify([]), {
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    }

    // --- CASE D: GENERAL PROXY ---
    const pathMap = {
        "status": "/api/status", "find_voice": "/api/find_voice", "global_stats": "/api/stats",
        "bot_guilds": "/api/bot_guilds", "join_guild": "/api/join_guild", "search": "/api/search",
        "user_info": "/api/user_info", "guild_settings": "/api/guild_settings", "control": "/api/control",
        "recommended": "/api/recommended"
    };

    if (!action && method === "GET") {
        return new Response(JSON.stringify({ status: "error", message: "Missing Action" }), {
            status: 400, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    }

    let targetPath = pathMap[action] || "/api/control";
    let targetUrl = new URL(VPS_API + targetPath);
    url.searchParams.forEach((v, k) => { if (k !== "action") targetUrl.searchParams.set(k, v); });

    try {
        const response = await fetch(targetUrl.toString(), {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: (method === "POST" || method === "PUT") ? bodyText : null
        });
        const respBody = await response.text();
        return new Response(respBody, {
            status: response.status,
            headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    } catch (err) {
        return new Response(JSON.stringify({ status: "error", message: "VPS Offline" }), {
            status: 502, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
        });
    }
}

function getDaysFromPlan(planId) {
    if (planId === "1_month") return 30;
    if (planId === "3_months") return 90;
    if (planId === "6_months") return 180;
    if (planId === "1_year") return 365;
    if (planId === "lifetime") return 36500;
    return 0;
}
