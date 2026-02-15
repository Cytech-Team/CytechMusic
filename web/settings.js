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

async function openSettings(id, name, icon) {
    currentGuildId = id;

    // Update URL with guild_id without reloading
    const newUrl = `${window.location.pathname}?guild_id=${id}${window.location.hash}`;
    window.history.pushState({ guild_id: id }, '', newUrl);

    // Switch Screen
    document.getElementById('server-selection-screen').style.display = 'none';
    document.getElementById('settings-content').style.display = 'block';

    // Set Header Info
    document.getElementById('guild-name').textContent = name;
    document.getElementById('guild-id').textContent = `ID: ${id}`;
    document.getElementById('guild-icon').src = icon;

    // Fetch Data
    fetchSettings(id);
}

function closeSettings() {
    document.getElementById('settings-content').style.display = 'none';
    document.getElementById('server-selection-screen').style.display = 'block';
    currentGuildId = null;

    // Clear guild_id from URL
    const cleanUrl = window.location.pathname + window.location.hash;
    window.history.pushState({}, '', cleanUrl);
}

async function fetchSettings(guildId) {
    // Reset inputs to loading state
    document.getElementById('setting-prefix').value = 'Loading...';

    try {
        const user = window.userProfile;
        if (!user) throw new Error("No user profile found");

        const res = await fetch(`${BOT_API}?action=guild_settings&guild_id=${guildId}&user_id=${user.id}`);
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        // Fill Form Data
        document.getElementById('setting-prefix').value = data.prefix || '!';
        document.getElementById('setting-lang').value = data.lang || 'en';
        document.getElementById('setting-247').checked = data.mode247 || false;
        document.getElementById('setting-autoplay').checked = data.autoplay || false;
        document.getElementById('setting-dj-mode').checked = data.dj_mode || false;

        // Populate Roles
        const roleSel = document.getElementById('setting-dj-role');
        roleSel.innerHTML = '<option value="">None</option>';
        if (data.roles && Array.isArray(data.roles)) {
            data.roles.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.id;
                opt.textContent = r.name;
                if (r.id === data.dj_role) opt.selected = true;
                roleSel.appendChild(opt);
            });
        }

    } catch (e) {
        console.error("[Settings] Fetch error:", e);
        document.getElementById('setting-prefix').value = 'Error';
        alert("Failed to load settings. Bot might be offline.");
    }
}

async function saveSettings() {
    if (!currentGuildId) return;

    const btn = document.querySelector('.save-bar');
    const oldHtml = btn.innerHTML;

    // UI Loading State
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    btn.disabled = true;
    btn.classList.add('btn-loading');

    const payload = {
        action: 'proxy_control',
        cmd_action: 'guild_settings_save',
        guild_id: currentGuildId,
        user_id: window.userProfile ? window.userProfile.id : null,
        settings: JSON.stringify({
            prefix: document.getElementById('setting-prefix').value,
            lang: document.getElementById('setting-lang').value,
            mode247: document.getElementById('setting-247').checked,
            autoplay: document.getElementById('setting-autoplay').checked,
            dj_mode: document.getElementById('setting-dj-mode').checked,
            dj_role: document.getElementById('setting-dj-role').value
        })
    };

    try {
        // Send as POST to GAS, with 'text/plain' to avoid CORS preflight issues if possible, or standard JSON
        const res = await fetch(BOT_API, {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain;charset=utf-8' }, // GAS hack for CORS
            body: JSON.stringify(payload)
        });
        const json = await res.json();

        if (json.status === 'ok' || json.status === 'success') {
            btn.classList.remove('btn-loading');
            btn.classList.add('btn-success');
            btn.innerHTML = '<i class="fas fa-check"></i> Saved!';

            setTimeout(() => {
                btn.classList.remove('btn-success');
                btn.innerHTML = oldHtml;
                btn.disabled = false;
            }, 2000);
        } else {
            throw new Error(json.error || 'Unknown Error');
        }
    } catch (e) {
        console.error(e);
        btn.classList.remove('btn-loading');
        btn.classList.add('btn-error');
        btn.innerHTML = '<i class="fas fa-times"></i> Failed';

        setTimeout(() => {
            btn.classList.remove('btn-error');
            btn.innerHTML = oldHtml;
            btn.disabled = false;
        }, 2000);
    }
}