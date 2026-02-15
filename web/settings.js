/* Server Settings Logic - Cyori (Full Version)
   Features: 
   - Server Selector with Priority Sorting (1-4)
   - Search Functionality
   - Settings Form (Fetch/Save via GAS Proxy)
*/

// --- CONFIGURATION ---
const BOT_API = "/api/proxy";
const BOT_INVITE_URL = "https://discord.com/api/oauth2/authorize?client_id=1469606905948405833&permissions=3533896&scope=bot%20applications.commands";

// --- STATE VARIABLES ---
let allGuilds = [];
let currentGuildId = null;

// ==========================================
// 1. INITIALIZATION & AUTH
// ==========================================

// เรียกโดย script.js เมื่อ Login สำเร็จ
function onUserLoggedIn(user) {
    if (user && user.id) {
        // ซ่อน Login Wall, แสดง Settings Container
        const wall = document.getElementById('login-wall');
        const container = document.getElementById('settings-container');
        if (wall) wall.style.display = 'none';
        if (container) container.style.display = 'block';

        // โหลดรายชื่อเซิร์ฟเวอร์
        loadServerList().then(() => {
            // เช็คว่ามี guild_id ใน URL ไหม เพื่อเปิดหน้าตั้งค่าทันที
            const urlParams = new URLSearchParams(window.location.search);
            const guildId = urlParams.get('guild_id');
            if (guildId) {
                const guild = allGuilds.find(g => g.id === guildId);
                if (guild && guild.actionType === 'manage') {
                    const iconUrl = guild.icon
                        ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png`
                        : 'logo-circle.png';
                    openSettings(guild.id, guild.name, iconUrl);
                }
            }
        });
    }
}

// ==========================================
// 2. SERVER LIST LOGIC
// ==========================================

async function loadServerList() {
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) return;

    // Show Loading
    const loader = document.getElementById('loading-servers');
    const grid = document.getElementById('server-grid');
    if (loader) loader.style.display = 'block';

    // 1. Try Cache First (Valid for 5 minutes)
    const cached = localStorage.getItem('cyori_server_list');
    const cacheTime = localStorage.getItem('cyori_server_list_time');

    if (cached && cacheTime && (Date.now() - cacheTime < 300000)) { // 5 min cache
        try {
            const data = JSON.parse(cached);
            if (loader) loader.style.display = 'none';
            renderServerList(data);
            // Background refresh if older than 1 min
            if (Date.now() - cacheTime > 60000) fetchServerListFresh(accessToken, grid, loader);
            return;
        } catch (e) { }
    }

    await fetchServerListFresh(accessToken, grid, loader);
}

async function fetchServerListFresh(accessToken, grid, loader) {
    try {
        // A. ดึงเซิร์ฟเวอร์ของ User จาก Discord API
        const userGuildsRes = await fetch('https://discord.com/api/users/@me/guilds', {
            headers: { Authorization: `Bearer ${accessToken}` }
        });

        if (!userGuildsRes.ok) throw new Error("Failed to fetch Discord guilds");
        const userGuilds = await userGuildsRes.json();

        // B. ดึงรายชื่อเซิร์ฟเวอร์ที่บอทอยู่ (จาก GAS -> Python)
        let botGuildIds = [];
        try {
            const botRes = await fetch(`${BOT_API}?action=bot_guilds`, { mode: 'cors' });
            const botData = await botRes.json();
            if (botData.guilds) botGuildIds = botData.guilds;
        } catch (e) {
            console.warn("[Settings] Bot fetch failed, assuming bot is offline or empty list.");
        }

        // C. ประมวลผลและจัดเรียง
        processAndSortGuilds(userGuilds, botGuildIds);

    } catch (e) {
        console.error("[Settings] Error:", e);
        if (loader) loader.innerHTML = `<p class="error-text">Failed to load servers. Please try logging in again.</p>`;
    }
}

function processAndSortGuilds(userGuilds, botGuildIds) {
    // Permission Constants (BigInt for precision)
    const PERM_ADMIN = BigInt(0x8);
    const PERM_MANAGE_GUILD = BigInt(0x20);

    allGuilds = userGuilds.map(guild => {
        // 1. Basic Info
        const isOwner = guild.owner;
        const perms = BigInt(guild.permissions);

        // 2. Permission Check (Admin OR Owner OR Manage Server)
        const isAdmin = (perms & PERM_ADMIN) === PERM_ADMIN;
        const isManager = (perms & PERM_MANAGE_GUILD) === PERM_MANAGE_GUILD;
        const hasPerm = isOwner || isAdmin || isManager;

        // 3. Bot Check
        const hasBot = botGuildIds.includes(guild.id);

        // --- SORTING LOGIC (1-4) ---
        let priority = 4;
        let statusText = "No Access";
        let subText = "";
        let actionType = "disabled";

        if (hasBot && hasPerm) {
            // 1. Bot & User are in guild + User has Perms -> Manage
            priority = 1;
            statusText = "Manageable";
            actionType = "manage";
        }
        else if (!hasBot && hasPerm) {
            // 2. Bot NOT in guild + User has Perms -> Invite
            priority = 2;
            statusText = "Invite Bot";
            actionType = "invite";
        }
        else if (hasBot && !hasPerm) {
            // 3. Bot & User in guild + User NO Perms -> No Permission
            priority = 3;
            statusText = "No Permission";
            actionType = "no_perm";
        }
        else {
            // 4. Bot NOT in guild + User NO Perms -> No Access
            priority = 4;
            statusText = "No Access";
            actionType = "disabled";
        }

        return { ...guild, isOwner, isAdmin, hasBot, priority, statusText, actionType };
    });

    // เรียงลำดับ: Priority น้อยขึ้นก่อน (1 -> 2 -> 3 -> 4)
    allGuilds.sort((a, b) => a.priority - b.priority);

    // Cache Result
    localStorage.setItem('cyori_server_list', JSON.stringify(allGuilds));
    localStorage.setItem('cyori_server_list_time', Date.now());

    renderServerList(allGuilds);
}

function renderServerList(guilds) {
    const container = document.getElementById('server-grid');
    const loader = document.getElementById('loading-servers');
    if (loader) loader.style.display = 'none';
    if (container) container.innerHTML = '';

    if (guilds.length === 0) {
        container.innerHTML = '<p class="no-servers-msg">No servers found.</p>';
        return;
    }

    guilds.forEach(guild => {
        const iconUrl = guild.icon
            ? `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png`
            : 'logo-circle.png';

        // Badges HTML
        let badges = '';
        if (guild.isOwner) badges += `<span class="badge badge-owner"><i class="fas fa-crown"></i> Owner</span>`;
        if (guild.isAdmin && !guild.isOwner) badges += `<span class="badge badge-admin" style="background: rgba(0, 150, 255, 0.15); color: #0096FF; border: 1px solid rgba(0, 150, 255, 0.3);"><i class="fas fa-user-shield"></i> Admin</span>`;
        if (guild.hasBot) badges += `<span class="badge badge-bot"><i class="fas fa-check"></i> Added</span>`;

        // Interaction Logic
        let onClick = '';
        let actionIcon = '';
        let statusText = guild.statusText;

        if (guild.actionType === 'manage') {
            onClick = `openSettings('${guild.id}', '${escapeName(guild.name)}', '${iconUrl}')`;
            actionIcon = '<i class="fas fa-cog"></i>';
        } else if (guild.actionType === 'invite') {
            onClick = `window.open('${BOT_INVITE_URL}&guild_id=${guild.id}', '_blank')`;
            actionIcon = '<i class="fas fa-plus"></i>';
        } else {
            actionIcon = '<i class="fas fa-lock"></i>';
        }

        // Generate HTML
        const html = `
            <div class="server-card priority-${guild.priority}" onclick="${onClick}">
                    <div class="server-icon-wrapper">
                        <img src="${iconUrl}" class="server-icon" alt="${guild.name}">
                        <div class="server-action-overlay">${actionIcon}</div>
                    </div>
                    <div class="server-info">
                        <div class="server-name">${guild.name}</div>
                        <div class="server-badges">${badges}</div>
                        <div class="server-status status-${guild.actionType}">
                            ${statusText}
                        </div>
                    </div>
            </div>
        `;
        container.innerHTML += html;
    });
}

function filterServers() {
    const query = document.getElementById('server-search').value.toLowerCase();
    const filtered = allGuilds.filter(g => g.name.toLowerCase().includes(query));
    renderServerList(filtered);
}

function escapeName(str) {
    return str.replace(/'/g, "\\'");
}

// ==========================================
// 3. SETTINGS FORM LOGIC
// ==========================================


// ==========================================
// 3. SETTINGS FORM LOGIC (Optimized & Instant)
// ==========================================

async function openSettings(id, name, icon) {
    currentGuildId = id;

    // Update URL logic...
    const newUrl = `${window.location.pathname}?guild_id=${id}${window.location.hash}`;
    window.history.pushState({ guild_id: id }, '', newUrl);

    // Switch Screen - INSTANT
    document.getElementById('server-selection-screen').style.display = 'none';
    document.getElementById('settings-content').style.display = 'block';

    // Set Header Info
    document.getElementById('guild-name').textContent = name;
    document.getElementById('guild-id').textContent = `ID: ${id}`;
    document.getElementById('guild-icon').src = icon;

    // 1. CACHE FIRST (Instant Load)
    const cacheKey = `guild_metrics_${id}`; // Using metrics key style or settings
    const cached = localStorage.getItem(cacheKey);

    if (cached) {
        try {
            const data = JSON.parse(cached);
            console.log("[Settings] Loaded from cache");
            fillSettingsForm(data);
        } catch (e) { console.error("Cache parse error", e); }
    } else {
        // Show loading placeholder only if no cache
        document.getElementById('setting-prefix').value = 'Loading...';
    }

    // 2. BACKGROUND FETCH (Revalidate)
    await fetchSettings(id);
}

function fillSettingsForm(data) {
    // Fill Form Data
    if (data.prefix) document.getElementById('setting-prefix').value = data.prefix || '!';
    if (data.lang) document.getElementById('setting-lang').value = data.lang || 'en';

    // Toggles
    if (data.mode247 !== undefined) document.getElementById('setting-247').checked = data.mode247;
    else if (data.always_on !== undefined) document.getElementById('setting-247').checked = data.always_on; // Compatibility

    if (data.autoplay !== undefined) document.getElementById('setting-autoplay').checked = data.autoplay;

    // DJ Mode
    const djMode = data.dj_mode !== undefined ? data.dj_mode : (data.dj_only !== undefined ? data.dj_only : false);
    document.getElementById('setting-dj-mode').checked = djMode;

    // Populate Roles (This is tricky to cache because role lists change)
    // We only update role list if data contains roles
    const roleSel = document.getElementById('setting-dj-role');
    if (data.roles && Array.isArray(data.roles)) {
        // Save current selection if re-filling
        const currentSel = roleSel.value;

        roleSel.innerHTML = '<option value="">None</option>';
        data.roles.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.id;
            opt.textContent = r.name;
            if (r.id === data.dj_role || r.id === currentSel) opt.selected = true;
            roleSel.appendChild(opt);
        });
    } else if (data.dj_role) {
        // If we have a role ID but no list, ensure it's selected roughly or wait for fetch
    }
}

async function fetchSettings(guildId) {
    try {
        const user = window.userProfile;
        if (!user) return; // Silent fail if no user

        const res = await fetch(`${BOT_API}?action=guild_settings&guild_id=${guildId}&user_id=${user.id}`);
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        // Update Cache
        localStorage.setItem(`guild_metrics_${guildId}`, JSON.stringify(data));

        // Update UI
        fillSettingsForm(data);

    } catch (e) {
        console.error("[Settings] Background Fetch error:", e);
        // Only show alert if input is still stuck on loading
        if (document.getElementById('setting-prefix').value === 'Loading...') {
            document.getElementById('setting-prefix').value = 'Error';
            // Optional: Toast "Network Error"
        }
    }
}

// OPTIMISTIC SAVE
async function saveSettings() {
    if (!currentGuildId) return;

    const btn = document.querySelector('.save-bar');
    const oldHtml = btn.innerHTML;

    // 1. COLLECT DATA
    const newSettings = {
        prefix: document.getElementById('setting-prefix').value,
        lang: document.getElementById('setting-lang').value,
        mode247: document.getElementById('setting-247').checked,
        autoplay: document.getElementById('setting-autoplay').checked,
        dj_mode: document.getElementById('setting-dj-mode').checked,
        dj_role: document.getElementById('setting-dj-role').value
    };

    // 2. UPDATE CACHE IMMEDIATELY (So user sees it next time instantly)
    try {
        const cacheKey = `guild_metrics_${currentGuildId}`;
        const cached = JSON.parse(localStorage.getItem(cacheKey) || '{}');
        const merged = { ...cached, ...newSettings }; // Merge with existing data (roles, etc)
        localStorage.setItem(cacheKey, JSON.stringify(merged));
    } catch (e) { }

    // 3. SHOW SUCCESS INSTANTLY (Optimistic UI)
    btn.innerHTML = '<i class="fas fa-check"></i> Saved!';
    btn.classList.add('btn-success');
    // Don't disable button to allow rapid edits

    setTimeout(() => {
        btn.classList.remove('btn-success');
        btn.innerHTML = oldHtml;
    }, 1500);

    // 4. SYNC TO SERVER (Background)
    const payload = {
        action: 'proxy_control',
        cmd_action: 'guild_settings_save',
        guild_id: currentGuildId,
        user_id: window.userProfile ? window.userProfile.id : null,
        settings: JSON.stringify(newSettings, (key, value) => {
            // sanitize or just pass raw
            return value;
        })
        // Note: The previous logic double stringified 'settings'. 
        // We will keep 'settings' as a string if the backend expects it.
        // Or if backend expects flat fields:
    };

    // Re-constructing structure to match previous implementation exactly
    // Previous: settings: JSON.stringify({...}) inside payload

    try {
        const res = await fetch(BOT_API, {
            method: 'POST',
            body: JSON.stringify(payload)
            // No need for text/plain hack usually if CORS is handled, but keeping if it was necessary
        });
        // We don't really care about response unless it's an error
        // But for UX, we already showed success.
    } catch (e) {
        console.error("Background Save Failed", e);
        // Maybe turn button red?
        btn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Sync Failed';
        btn.classList.add('btn-error');
        setTimeout(() => {
            btn.classList.remove('btn-error');
            btn.innerHTML = oldHtml;
        }, 3000);
    }
}