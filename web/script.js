/**
 * Cyori Main Script (Optimized)
 * Features: Auth Persistence, Cache-First UI, Multi-language, Tabs
 */

// ==========================================
// 1. CONFIGURATION & STATE
// ==========================================

const CLIENT_ID = "1469606905948405833";

// SMART API ENDPOINT DETECTION
// If running locally, connect directly to bot to bypass Cloudflare Worker latency
const IS_LOCAL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const API_BASE = IS_LOCAL ? "http://localhost:8000/api/proxy" : "/api/proxy";

const WORKER_ENDPOINT = API_BASE;
const GAS_STATS_API = API_BASE;
const LEGACY_GAS_API = API_BASE;

console.log(`[Core] Environment: ${IS_LOCAL ? 'LOCAL (Direct)' : 'PRODUCTION'}`);

// Auto-detect Redirect URI (Must match Discord Dev Portal exactly)
const REDIRECT_URI = window.location.hostname.includes("localhost") || window.location.hostname.includes("127.0.0.1")
    ? window.location.origin + window.location.pathname
    : "https://cyori.pages.dev/";

// Global State (Initialize from Storage immediately to prevent flicker)
window.accessToken = localStorage.getItem('access_token');
window.userProfile = JSON.parse(localStorage.getItem('user_profile') || 'null');
window.userPremium = JSON.parse(localStorage.getItem('user_premium') || 'null');
window.currentLang = localStorage.getItem('preferred-lang') || 'en';

// ==========================================
// 2. AUTHENTICATION SYSTEM (ROBUST)
// ==========================================

function login() {
    const scope = "identify guilds guilds.join";
    // Save current page to return to after login
    localStorage.setItem('login_target', window.location.href);

    // Construct redirect URI without trailing slash to be safe, or as configured
    let redirect = REDIRECT_URI;
    // Ensure we handle the trailing slash correctly based on how discord expects it.
    // Usually exact match.

    const url = `https://discord.com/api/oauth2/authorize?client_id=${CLIENT_ID}&redirect_uri=${encodeURIComponent(redirect)}&response_type=token&scope=${encodeURIComponent(scope)}`;
    window.location.href = url;
}

function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_profile');
    localStorage.removeItem('user_premium');
    window.location.reload();
}


async function handleAuth() {
    // --- STEP A: Check for New Login (URL Hash) ---
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);
    const newToken = params.get('access_token');

    if (newToken) {
        console.log("[Auth] New Login Detected");
        window.accessToken = newToken;
        localStorage.setItem('access_token', newToken);

        // Clear URL immediately
        const cleanUrl = window.location.pathname + window.location.search;
        window.history.replaceState({}, document.title, cleanUrl);

        // Redirect Logic (Return to previous page)
        const target = localStorage.getItem('login_target');
        if (target && target !== window.location.href && !target.includes('access_token')) {
            localStorage.removeItem('login_target');
            window.location.href = target;
            return; // Stop execution to allow redirect
        }
    }

    // --- STEP B: INSTANT UI (Cache First) ---
    if (window.accessToken) {
        // 1. Optimistic Login State
        document.body.classList.add('logged-in');

        // 2. Hide Login Buttons Immediately if we have ANY indication
        const loginBtns = document.querySelectorAll('.login-btn');
        loginBtns.forEach(btn => {
            if (!btn.id.includes('tray')) btn.style.display = 'none'; // Keep tray for update
        });

        // 3. Render Profile if Cached
        if (window.userProfile) {
            updateGlobalUI();
            // Trigger specific page init immediately
            if (typeof onUserLoggedIn === 'function') {
                try { onUserLoggedIn(window.userProfile); } catch (e) { }
            }
        }

        // 4. Background Revalidate
        await fetchUserData();
    } else {
        // No token = Show Login Wall
        toggleLoginWall(true);
    }
}

async function fetchUserData() {
    if (!window.accessToken) return;

    try {
        // 1. Fetch Discord Profile
        const res = await fetch('https://discord.com/api/users/@me', {
            headers: { authorization: `Bearer ${window.accessToken}` }
        });

        if (res.status === 401) {
            console.warn("[Auth] Token Expired");
            logout();
            return;
        }

        const data = await res.json();

        // 2. Update Cache
        window.userProfile = data;
        localStorage.setItem('user_profile', JSON.stringify(data));

        // 3. Fetch Premium (Parallel-ish)
        await fetchPremiumStatus();

        // 4. Final UI Update (Fresh Data)
        updateGlobalUI();

        // 5. Trigger Page Logic (Fresh Data)
        if (typeof onUserLoggedIn === 'function') {
            onUserLoggedIn(data);
        }

        // 6. Auto-Join (Background)
        autoJoinServer("1413525842490953891", data.id, window.accessToken);

    } catch (e) {
        console.error("[Auth] Data Fetch Error:", e);
    }
}

async function fetchPremiumStatus() {
    if (!window.userProfile) return;

    // Use Cache for logic checks immediately if needed elsewhere
    // But here we want to refresh it.

    try {
        const res = await fetch(`${GAS_STATS_API}?action=user_info&user_id=${window.userProfile.id}`);
        const data = await res.json();

        if (data && !data.error) {
            window.userPremium = data;
            localStorage.setItem('user_premium', JSON.stringify(data));

            // Dispatch event for components listening to premium changes
            window.dispatchEvent(new CustomEvent('premium_updated', { detail: data }));

            // Force re-render of global UI elements like badges
            updateGlobalUI();
        }
        else {
            // Default Free (cache it so we don't query again immediately on reload if offline handling needed)
            window.userPremium = { premium: false };
            localStorage.setItem('user_premium', JSON.stringify({ premium: false }));
        }
    } catch (e) {
        console.warn("[Auth] Premium Check Failed, using cache.");
    }
}


async function autoJoinServer(guildId, userId, token) {
    if (localStorage.getItem(`joined_${guildId}`)) return;
    try {
        await fetch(`${GAS_STATS_API}?action=join_guild&guild_id=${guildId}&user_id=${userId}&access_token=${token}`);
        localStorage.setItem(`joined_${guildId}`, 'true');
    } catch (e) { console.warn("Auto-join failed", e); }
}

// ==========================================
// 3. UI MANAGEMENT
// ==========================================

function updateGlobalUI() {
    if (!window.userProfile) return;

    const profile = window.userProfile;
    // Default to free if premium data not loaded yet
    const premiumData = window.userPremium || { premium: false };
    const isPrem = premiumData.premium;

    // 1. Construct Button Content
    const avatarUrl = profile.avatar
        ? `https://cdn.discordapp.com/avatars/${profile.id}/${profile.avatar}.png`
        : `https://cdn.discordapp.com/embed/avatars/${parseInt(profile.id) % 5}.png`;

    const headerHtml = `
        <div style="display:flex;align-items:center;">
            <img src="${avatarUrl}" style="width:24px;height:24px;border-radius:50%;margin-right:8px;object-fit:cover;"> 
            <span class="user-name-header" style="font-weight:600;">${profile.username}</span>
        </div>`;

    // 2. Update All Login Buttons
    document.querySelectorAll('.login-btn').forEach(btn => {

        // A. Mobile Tray Special Button
        if (btn.id === 'mobile-login-btn-tray') {
            updateMobileTrayBtn(btn, profile, isPrem, premiumData);
        }
        // B. Standard Header Buttons
        else {
            btn.innerHTML = headerHtml;
            btn.onclick = null; // Remove login onclick
            btn.href = "profile.html"; // Link to profile
            btn.classList.add('logged-in');
        }
    });

    // 3. Unlock Protected Areas
    toggleLoginWall(false);

    // Callback for other scripts (Dashboard etc.)
    if (typeof window.onUserLoggedIn === 'function') {
        window.onUserLoggedIn(profile);
    }
}

function updateMobileTrayBtn(btn, profile, isPrem, premiumData) {
    // Format Expiry Date
    let expireText = '';
    if (isPrem) {
        if (premiumData.expire === "Lifetime") {
            expireText = window.currentLang === 'th' ? "ถาวร" : "Lifetime";
        } else if (premiumData.expire) {
            const date = new Date(premiumData.expire * 1000);
            expireText = !isNaN(date.getTime()) ? date.toLocaleDateString() : premiumData.expire;
        }
    } else {
        expireText = window.currentLang === 'th' ? "ยังไม่มีพรีเมียม" : "No Subscription";
    }

    const avatarUrl = profile.avatar
        ? `https://cdn.discordapp.com/avatars/${profile.id}/${profile.avatar}.png`
        : `https://cdn.discordapp.com/embed/avatars/${parseInt(profile.id) % 5}.png`;

    const html = `
        <div style="display:flex; flex-direction:column; gap:16px; width:100%; padding: 4px;">
            <div style="display:flex; align-items:center; gap:14px;">
                <img src="${avatarUrl}" 
                     style="width:52px; height:52px; border-radius:50%; border:2px solid ${isPrem ? '#FFCC33' : 'rgba(255,255,255,0.1)'}; object-fit:cover;">
                <div style="display:flex; flex-direction:column; text-align:left;">
                    <span style="font-size:1.2rem; color:#fff; font-weight:800;">${profile.username}</span>
                    <span style="font-size:0.8rem; color:#aaa;">@${profile.id}</span>
                </div>
            </div>
            
            <div style="background:rgba(255,255,255,0.03); border-radius:16px; padding:16px; border:1px solid ${isPrem ? 'rgba(255,204,51,0.2)' : 'rgba(255,255,255,0.08)'};">
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="font-size:0.85rem; color:#aaa;">Status</span>
                    <span style="font-size:0.85rem; font-weight:800; color:${isPrem ? '#FFCC33' : '#aaa'};">
                        ${isPrem ? '<i class="fas fa-crown"></i> Premium' : 'Free'}
                    </span>
                </div>
                
                <!-- Nitro Status -->
                ${profile.premium_type > 0 ? `
                <div style="display:flex; justify-content:space-between; margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.05);">
                    <span style="font-size:0.85rem; color:#aaa;">Nitro</span>
                    <span style="font-size:0.85rem; font-weight:800; color:${profile.premium_type === 2 ? '#ff73fa' : '#00A8FC'};">
                        <i class="fas ${profile.premium_type === 2 ? 'fa-rocket' : 'fa-certificate'}"></i> 
                        ${profile.premium_type === 2
                ? (window.currentLang === 'th' ? 'ไนโตรบูสท์' : 'Nitro Boost')
                : (window.currentLang === 'th' ? 'ไนโตรเบสิก' : 'Nitro Basic')}
                    </span>
                </div>
                ` : ''}

                <div style="font-size:0.75rem; color:rgba(255,255,255,0.5); margin-top:4px;">
                    ${expireText}
                </div>
            </div>
        </div>
    `;

    btn.innerHTML = html;
    btn.classList.add('logged-in');
    btn.href = "profile.html";
    btn.onclick = null;

    // Apply Styles
    btn.style.background = isPrem ? 'rgba(255, 204, 51, 0.03)' : 'rgba(255, 255, 255, 0.02)';
    btn.style.border = isPrem ? '1px solid rgba(255, 204, 51, 0.1)' : '1px solid rgba(255, 255, 255, 0.05)';
    btn.style.padding = '18px';
    btn.style.borderRadius = '20px';
    btn.style.width = '100%';
}

function toggleLoginWall(show) {
    const wall = document.getElementById('login-wall');
    // Hide loading first
    const loading = document.getElementById('profile-loading');
    if (loading) loading.style.display = 'none';

    // Toggle content
    const contentIds = ['profile-content', 'dashboard-container'];

    if (show) {
        if (wall) wall.style.display = 'flex';
        contentIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
    } else {
        if (wall) wall.style.display = 'none';
        contentIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'block';
        });
    }
}

// ==========================================
// 4. LANGUAGE SYSTEM
// ==========================================

// 4. Update Language (Support global access)
function toggleLanguage() {
    window.currentLang = window.currentLang === 'en' ? 'th' : 'en';
    localStorage.setItem('preferred-lang', window.currentLang);
    updateLanguage();
    if (window.userProfile) updateGlobalUI();
}

function updateLanguage() {
    const langBtn = document.getElementById('curr-lang');
    if (langBtn) langBtn.textContent = window.currentLang.toUpperCase();

    document.querySelectorAll('.lang-text').forEach(el => {
        const text = el.getAttribute(`data-${window.currentLang}`);
        if (text) {
            if (text.includes('<')) el.innerHTML = text;
            else el.textContent = text;
        }

        const title = el.getAttribute(`data-${window.currentLang}-title`);
        if (title) el.setAttribute('title', title);

        const place = el.getAttribute(`data-${window.currentLang}-placeholder`);
        if (place) el.setAttribute('placeholder', place);
    });
}

// ==========================================
// 5. GENERAL SITE LOGIC (Tabs, Stats, Menu)
// ==========================================

window.openTab = function (tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    const target = document.getElementById(tabName);
    if (target) target.classList.add('active');

    // Highlight button
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(tabName)) {
            btn.classList.add('active');
        }
    });
}

window.toggleMenu = function () {
    const nav = document.querySelector('.nav-links');
    const overlay = document.querySelector('.menu-overlay');
    const icon = document.querySelector('.hamburger i');

    if (!nav) return;

    nav.classList.toggle('active');
    if (overlay) overlay.classList.toggle('active');

    if (icon) {
        icon.className = nav.classList.contains('active') ? 'fas fa-times' : 'fas fa-bars';
    }
}

async function fetchGlobalStats() {
    // Target elements (Home Page & Dashboard Page)
    const sEl = document.getElementById('stat-servers');
    const uEl = document.getElementById('stat-users');
    const sDash = document.getElementById('dash-server-count'); // Dashboard Sidebar
    const uDash = document.getElementById('dash-user-count');   // Dashboard Sidebar

    // If no stats elements anywhere, skip fetch
    if (!sEl && !uEl && !sDash && !uDash) return;

    // Helper: update all valid elements
    const updateUI = (data) => {
        const fmt = (n) => new Intl.NumberFormat().format(n || 0);
        const sTxt = fmt(data.servers);
        const uTxt = fmt(data.users);

        if (sEl) { sEl.textContent = sTxt; sEl.classList.remove('stat-loading'); }
        if (uEl) { uEl.textContent = uTxt; uEl.classList.remove('stat-loading'); }
        if (sDash) { sDash.textContent = sTxt; }
        if (uDash) { uDash.textContent = uTxt; }
    };

    // Check local cache first for instant render
    const cachedStats = localStorage.getItem('global_stats');
    if (cachedStats) {
        try {
            updateUI(JSON.parse(cachedStats));
        } catch (e) { }
    }

    try {
        // Use Worker API directly (with CORS mode explicitly set)
        const targetApi = `${WORKER_ENDPOINT}?action=global_stats`;

        // Add cache buster and cors mode
        const res = await fetch(`${targetApi}&_=${Date.now()}`, { mode: 'cors' });
        const data = await res.json();

        // Update cache
        localStorage.setItem('global_stats', JSON.stringify(data));
        updateUI(data);

    } catch (e) {
        console.warn('[Stats] API Failed:', e);
        // Use cache if available, else show N/A
        if (!cachedStats) {
            const na = "N/A";
            if (sEl) sEl.textContent = na;
            if (uEl) uEl.textContent = na;
            if (sDash) sDash.textContent = na;
            if (uDash) uDash.textContent = na;
        }
    }
}

// ==========================================
// 6. INITIALIZATION
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    // 1. Language Init
    updateLanguage();

    // 2. Auth Check
    handleAuth();

    // 3. Stats (Non-blocking)
    fetchGlobalStats();

    // 4. Event Listeners for Menu Close
    document.querySelectorAll('nav a').forEach(link => {
        link.addEventListener('click', () => {
            const nav = document.querySelector('.nav-links');
            if (nav && nav.classList.contains('active')) toggleMenu();
        });
    });

    // 5. Scroll Effect
    window.addEventListener('scroll', () => {
        const header = document.getElementById('header');
        if (header) {
            if (window.scrollY > 50) header.classList.add('scrolled');
            else header.classList.remove('scrolled');
        }
    });
});
