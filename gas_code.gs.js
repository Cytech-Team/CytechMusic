// ==========================================
// Cyori Payment Middleware (Google Apps Script) - DYNAMIC PROXY VERSION
// ==========================================
// 1. Create a new Google Apps Script project (script.google.com)
// 2. Paste this code
// 3. Project Settings > Script Properties: Add 'STRIPE_SECRET_KEY' (sk_live_...)
// 4. Deploy > New Deployment > Web App > Execute as: Me > Who has access: Anyone
// 5. Copy the Deployment URL and put it in 'payment.js' and your Bot's .env (STRIPE_PROXY_URL)

const STRIPE_SECRET_KEY = PropertiesService.getScriptProperties().getProperty("STRIPE_SECRET_KEY");

// --- CONFIGURATION ---
// Default Fallback (Cloudflare Tunnel - High Performance)
const DEFAULT_BOT_API = "https://YOUR_TUNNEL_URL";
const SUCCESS_URL = "https://cyori.pages.dev/success.html";

// Plan Configuration (Must match payment.py)
const PLANS = {
  "1_month": { price: 2900, name: "Premium (1 Month)" },
  "3_months": { price: 7900, name: "Premium (3 Months)" },
  "6_months": { price: 14900, name: "Premium (6 Months)" },
  "1_year": { price: 28900, name: "Premium (1 Year)" },
  "lifetime": { price: 78900, name: "Premium (Lifetime)" }
};

// ==========================================
// DYNAMIC ROUTING & QUEUE HELPERS
// ==========================================

function pushToQueue(event) {
  const props = PropertiesService.getScriptProperties();
  let queue = JSON.parse(props.getProperty("EVENT_QUEUE") || "[]");
  queue.push({
    id: Utilities.getUuid(),
    timestamp: new Date().getTime(),
    data: event
  });
  // Keep only last 20 events to save space
  if (queue.length > 20) queue.shift();
  props.setProperty("EVENT_QUEUE", JSON.stringify(queue));
}

function getQueueFromGAS() {
  const props = PropertiesService.getScriptProperties();
  const queue = props.getProperty("EVENT_QUEUE") || "[]";
  props.setProperty("EVENT_QUEUE", "[]"); // Clear after read
  return queue;
}

function getActiveBotApi() {
  const props = PropertiesService.getScriptProperties();
  return props.getProperty("ACTIVE_BOT_API") || DEFAULT_BOT_API;
}

function getAllRegisteredBots() {
  const props = PropertiesService.getScriptProperties();
  const bots = props.getProperty("REGISTERED_BOTS");
  return bots ? JSON.parse(bots) : [DEFAULT_BOT_API];
}

function registerBot(url) {
  const props = PropertiesService.getScriptProperties();
  // Set as the current active bot for Dashboard
  props.setProperty("ACTIVE_BOT_API", url);

  // Add to broadcast list for Webhooks
  let bots = getAllRegisteredBots();
  if (!bots.includes(url)) {
    bots.push(url);
    props.setProperty("REGISTERED_BOTS", JSON.stringify(bots));
  }
  return createJSONOutput({ status: "success", registered: url });
}

// ==========================================
// MAIN ENTRY POINTS
// ==========================================

function doPost(e) {
  if (e.postData && (e.postData.type.includes("json") || IsJsonString(e.postData.contents))) {
    const data = JSON.parse(e.postData.contents);

    // 0. Bot Dynamic Registration
    if (data.action === "register_bot") {
      return registerBot(data.url);
    }

    // 1. Dashboard Control (Pause, Skip, Volume, etc.)
    if (data.action === "proxy_control" || (data.guild_id && data.action)) {
      // Also push to queue for Polling bots
      pushToQueue({ type: "control", payload: data });
      return handleProxyControl(data);
    }

    // 2. Checkout Creation (Payment Page)
    if (data.action === "create_checkout") {
      return handleCheckoutCreation(data);
    }

    // 4. GitHub Webhook (Dynamic Tracking)
    if (e.postData.contents.includes("repository") && e.postData.contents.includes("commits")) {
      const gitData = {
        type: "github_push",
        repo: data.repository.full_name,
        author: data.commits[0].author.name,
        message: data.commits[0].message,
        url: data.commits[0].url
      };
      pushToQueue(gitData);
      return handleGitHubWebhook(data);
    }
  }

  // 3. Fallback: Stripe Webhook Forwarding (Broadcast Mode)
  return handleStripeWebhook(e);
}

function doGet(e) {
  if (!e.parameter) return ContentService.createTextOutput("Cyori Proxy Active");

  const action = e.parameter.action;

  // NEW: Polling Endpoint for bots without Public Address
  if (action === "poll") {
    return createJSONResponse(getQueueFromGAS());
  }

  const botApi = getActiveBotApi();

  if (action === "status") return handleProxyGet(botApi, "/api/status", { guild_id: e.parameter.guild_id });
  if (action === "find_voice") return handleProxyGet(botApi, "/api/find_voice", { user_id: e.parameter.user_id });
  if (action === "global_stats") return handleProxyGet(botApi, "/api/stats");
  if (action === "bot_guilds") return handleProxyGet(botApi, "/api/bot_guilds");
  if (action === "join_guild") return handleProxyGet(botApi, "/api/join_guild", { guild_id: e.parameter.guild_id, user_id: e.parameter.user_id, token: e.parameter.access_token || e.parameter.token });
  if (action === "search") return handleProxyGet(botApi, "/api/search", { query: e.parameter.query, guild_id: e.parameter.guild_id });
  if (action === "user_info") return handleProxyGet(botApi, "/api/user_info", { user_id: e.parameter.user_id });
  if (action === "guild_settings") return handleProxyGet(botApi, "/api/guild_settings", { guild_id: e.parameter.guild_id, user_id: e.parameter.user_id });

  return ContentService.createTextOutput("Cyori Proxy Ready | Active: " + botApi);
}

// ==========================================
// HANDLERS
// ==========================================

function handleProxyGet(api, path, params = {}) {
  try {
    let queryString = Object.keys(params).map(k => k + "=" + encodeURIComponent(params[k])).join("&");
    const fullUrl = api + path + (queryString ? "?" + queryString : "");
    const response = UrlFetchApp.fetch(fullUrl, { muteHttpExceptions: true });
    return createJSONResponse(response.getContentText());
  } catch (err) {
    // FAILOVER: If dynamic API fails, try the Production Default
    if (api !== DEFAULT_BOT_API) {
      console.warn("Active Bot failed, falling back to default:", api);
      return handleProxyGet(DEFAULT_BOT_API, path, params);
    }
    return createJSONOutput({ error: "Bot unreachable at " + api });
  }
}

function handleProxyControl(data) {
  const botApi = data.force_default ? DEFAULT_BOT_API : getActiveBotApi();
  try {
    const action = data.cmd_action || data.action;
    const eventId = data.event_id || Utilities.getUuid();
    let targetUrl = `${botApi}/api/control`;
    let payload = {
      guild_id: data.guild_id,
      user_id: data.user_id,
      action: action,
      value: data.value,
      event_id: eventId // Provide ID for de-duplication
    };

    if (action === "guild_settings") {
      targetUrl = `${botApi}/api/guild_settings`;
      payload = {
        guild_id: data.guild_id,
        user_id: data.user_id,
        settings: data.settings
      };
    }

    const response = UrlFetchApp.fetch(targetUrl, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    return createJSONResponse(response.getContentText());
  } catch (err) {
    // FAILOVER: If dynamic API fails, try the Production Default
    if (botApi !== DEFAULT_BOT_API) {
      console.warn("Active Bot POST failed, falling back to default:", botApi);
      // Construct a new data object mimicking the original request for the fallback call
      return handleProxyControl({ ...data, force_default: true });
    }
    return createJSONOutput({ error: "Cannot forward control to " + botApi + ": " + err.toString() });
  }
}

// HANDLER: GitHub Webhook (Broadcast update notice to bots)
function handleGitHubWebhook(data) {
  const bots = getAllRegisteredBots();
  const repoName = data.repository.full_name;
  const lastCommit = data.commits[0];

  const broadcastData = {
    type: "github_push",
    repo: repoName,
    author: lastCommit.author.name,
    message: lastCommit.message,
    url: lastCommit.url
  };

  let results = [];
  bots.forEach(botApi => {
    try {
      UrlFetchApp.fetch(botApi + "/api/webhook/github", {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify(broadcastData),
        muteHttpExceptions: true
      });
      results.push(botApi + ": Broadcasted");
    } catch (err) {
      results.push(botApi + ": Error (" + err.toString() + ")");
    }
  });

  return ContentService.createTextOutput("GitHub Sync Broadcasted:\n" + results.join("\n"));
}

// HANDLER: Stripe Webhook (Broadcast to ALL registered bots)
function handleStripeWebhook(e) {
  const bots = getAllRegisteredBots();
  let results = [];

  bots.forEach(botApi => {
    try {
      const url = botApi + (botApi.endsWith("/") ? "" : "/") + "stripe/webhook";
      UrlFetchApp.fetch(url, {
        "method": "post",
        "contentType": "application/json",
        "payload": e.postData.contents,
        "muteHttpExceptions": true
      });
      results.push(botApi + ": OK");
    } catch (err) {
      results.push(botApi + ": Failed (" + err.toString() + ")");
    }
  });

  return ContentService.createTextOutput("Webhook Broadcast Results:\n" + results.join("\n"));
}

function handleCheckoutCreation(data) {
  try {
    const plan = PLANS[data.plan_id];
    if (!plan) return createJSONOutput({ status: "error", message: "Invalid plan" });
    const session = createStripeSession(data.user_id, data.plan_id, plan);
    if (session.error) return createJSONOutput({ status: "error", message: "Stripe Error: " + session.error.message });
    return createJSONOutput({ status: "success", clientSecret: session.client_secret });
  } catch (err) {
    return createJSONOutput({ status: "error", message: err.toString() });
  }
}

// ==========================================
// HELPERS
// ==========================================

function createStripeSession(userId, planId, plan) {
  const url = "https://api.stripe.com/v1/checkout/sessions";
  const payload = {
    "ui_mode": "embedded",
    "return_url": SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
    "mode": "payment",
    "payment_method_types[0]": "card",
    "payment_method_types[1]": "promptpay",
    "line_items[0][price_data][currency]": "thb",
    "line_items[0][price_data][product_data][name]": plan.name,
    "line_items[0][price_data][unit_amount]": plan.price.toString(),
    "line_items[0][quantity]": "1",
    "metadata[user_id]": userId.toString(),
    "metadata[plan_id]": planId,
    "metadata[days]": getDaysFromPlan(planId).toString()
  };
  const options = {
    "method": "post",
    "headers": { "Authorization": "Bearer " + STRIPE_SECRET_KEY },
    "payload": payload,
    "muteHttpExceptions": true
  };
  const response = UrlFetchApp.fetch(url, options);
  return JSON.parse(response.getContentText());
}

function getDaysFromPlan(planId) {
  if (planId === "1_month") return 30;
  if (planId === "3_months") return 90;
  if (planId === "6_months") return 180;
  if (planId === "1_year") return 365;
  if (planId === "lifetime") return 36500;
  return 0;
}

function createJSONOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function createJSONResponse(jsonString) {
  return ContentService.createTextOutput(jsonString).setMimeType(ContentService.MimeType.JSON);
}

function IsJsonString(str) {
  try { JSON.parse(str); } catch (e) { return false; }
  return true;
}
