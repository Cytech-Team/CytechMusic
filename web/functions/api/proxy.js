/**
 * CytechMusic Cloudflare Pages API proxy.
 *
 * Community builds are fail-closed: no Cyori/Cytech production endpoint is used
 * unless the deployer explicitly sets VPS_API_URL (or BOT_API_URL).
 */

const PLANS = {
    "1_month": { price: 2900, name: "Premium (1 Month)" },
    "3_months": { price: 7900, name: "Premium (3 Months)" },
    "6_months": { price: 14900, name: "Premium (6 Months)" },
    "1_year": { price: 28900, name: "Premium (1 Year)" },
    "lifetime": { price: 78900, name: "Premium (Lifetime)" },
};

function backendBase(env) {
    const value = env.VPS_API_URL || env.BOT_API_URL || "";
    return value ? value.replace(/\/+$/, "") : null;
}

function corsHeaders(request, env) {
    const requestOrigin = request.headers.get("Origin");
    const allowedOrigin = env.DASHBOARD_ORIGIN || new URL(request.url).origin;
    const origin = !requestOrigin || requestOrigin === allowedOrigin ? allowedOrigin : "null";
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Vary": "Origin",
    };
}

function jsonResponse(request, env, data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { "Content-Type": "application/json", ...corsHeaders(request, env) },
    });
}

function bearerToken(request) {
    const auth = request.headers.get("Authorization") || "";
    return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

async function verifyDiscordUser(request) {
    const token = bearerToken(request);
    if (!token) return null;
    try {
        const response = await fetch("https://discord.com/api/users/@me", {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return null;
        const user = await response.json();
        return user && user.id ? user : null;
    } catch (_) {
        return null;
    }
}

function forwardedHeaders(request, env, { webhook = false } = {}) {
    const headers = new Headers();
    const contentType = request.headers.get("Content-Type");
    if (contentType) headers.set("Content-Type", contentType);

    const auth = request.headers.get("Authorization");
    if (auth) headers.set("Authorization", auth);

    if (env.DASHBOARD_SECRET) {
        headers.set("X-Dashboard-Secret", env.DASHBOARD_SECRET);
    }

    if (webhook) {
        for (const name of ["stripe-signature", "x-github-event", "x-hub-signature-256", "x-github-delivery"]) {
            const value = request.headers.get(name);
            if (value) headers.set(name, value);
        }
    }
    return headers;
}

export async function onRequest(context) {
    const { request, env } = context;
    const url = new URL(request.url);
    const method = request.method;
    const cors = corsHeaders(request, env);

    if (method === "OPTIONS") {
        return new Response(null, { status: 204, headers: cors });
    }

    let bodyText = "";
    let bodyData = null;
    if (["POST", "PUT", "PATCH"].includes(method)) {
        try {
            bodyText = await request.text();
            if (bodyText) bodyData = JSON.parse(bodyText);
        } catch (_) {
            return jsonResponse(request, env, { error: "invalid_json" }, 400);
        }
    }

    const action = url.searchParams.get("action") || (bodyData && bodyData.action);
    const backend = backendBase(env);

    // Stripe checkout is handled at the edge, but identity comes only from Discord.
    if (action === "create_checkout") {
        const verifiedUser = await verifyDiscordUser(request);
        if (!verifiedUser) {
            return jsonResponse(request, env, { error: "unauthorized" }, 401);
        }

        const stripeKey = env.STRIPE_SECRET_KEY;
        if (!stripeKey) {
            return jsonResponse(request, env, { error: "stripe_not_configured" }, 503);
        }

        const planId = bodyData && bodyData.plan_id;
        const plan = PLANS[planId];
        if (!plan) {
            return jsonResponse(request, env, { error: "invalid_plan" }, 400);
        }

        try {
            const successUrl = env.SUCCESS_URL || `${url.origin}/success.html`;
            const stripeParams = new URLSearchParams({
                "ui_mode": "embedded",
                "return_url": `${successUrl}?session_id={CHECKOUT_SESSION_ID}`,
                "mode": "payment",
                "payment_method_types[0]": "card",
                "payment_method_types[1]": "promptpay",
                "line_items[0][price_data][currency]": "thb",
                "line_items[0][price_data][product_data][name]": plan.name,
                "line_items[0][price_data][unit_amount]": plan.price.toString(),
                "line_items[0][quantity]": "1",
                "metadata[user_id]": String(verifiedUser.id),
                "metadata[plan_id]": planId,
                "metadata[days]": String(getDaysFromPlan(planId)),
            });

            const stripeRes = await fetch("https://api.stripe.com/v1/checkout/sessions", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${stripeKey}`,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: stripeParams.toString(),
            });
            const session = await stripeRes.json();
            if (!stripeRes.ok || session.error) {
                throw new Error(session.error?.message || `Stripe HTTP ${stripeRes.status}`);
            }
            return jsonResponse(request, env, {
                status: "success",
                clientSecret: session.client_secret,
            });
        } catch (error) {
            return jsonResponse(request, env, { error: "stripe_error", message: String(error.message || error) }, 502);
        }
    }

    // Never silently accept or drop webhook authenticity headers.
    const isGithub = request.headers.get("x-github-event");
    const stripeSignature = request.headers.get("stripe-signature");
    if (isGithub || stripeSignature) {
        if (!backend) {
            return jsonResponse(request, env, { error: "backend_not_configured" }, 503);
        }
        const target = isGithub
            ? `${backend}/api/webhook/github`
            : `${backend}/stripe/webhook`;
        try {
            const response = await fetch(target, {
                method: "POST",
                headers: forwardedHeaders(request, env, { webhook: true }),
                body: bodyText,
            });
            return new Response(await response.text(), {
                status: response.status,
                headers: { "Content-Type": response.headers.get("Content-Type") || "text/plain", ...cors },
            });
        } catch (_) {
            return jsonResponse(request, env, { error: "backend_unreachable" }, 502);
        }
    }

    if (action === "register_bot") {
        return jsonResponse(request, env, { status: "success", info: "static proxy" });
    }
    if (action === "poll") {
        return jsonResponse(request, env, []);
    }

    if (!backend) {
        return jsonResponse(request, env, {
            error: "backend_not_configured",
            message: "Set VPS_API_URL (or BOT_API_URL) for this Community deployment.",
        }, 503);
    }

    const targetUrl = new URL(`${backend}/api/proxy`);
    url.searchParams.forEach((value, key) => targetUrl.searchParams.set(key, value));

    try {
        const response = await fetch(targetUrl.toString(), {
            method,
            headers: forwardedHeaders(request, env),
            body: ["POST", "PUT", "PATCH"].includes(method) ? bodyText : null,
        });
        return new Response(await response.text(), {
            status: response.status,
            headers: {
                "Content-Type": response.headers.get("Content-Type") || "application/json",
                ...cors,
            },
        });
    } catch (_) {
        return jsonResponse(request, env, { error: "backend_unreachable" }, 502);
    }
}

function getDaysFromPlan(planId) {
    const map = { "1_month": 30, "3_months": 90, "6_months": 180, "1_year": 365, "lifetime": 36500 };
    return map[planId] ?? 0;
}
