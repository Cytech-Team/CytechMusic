/* 
   Dashboard Logic - Cyori (Unified & Fixed)
*/

// ==========================================
// CONFIGURATION
// ==========================================
// --- ZERO-DELAY INTERNAL RUNNER ---
// ยิงเข้าหาตัวเอง (Pages Function) เพื่อประหยัดเวลาและไม่มี Delay
const IS_LOCAL_DASH = window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.protocol === 'file:' ||
    window.location.hostname === '';

const BOT_API = IS_LOCAL_DASH ? "http://localhost:8000/api/proxy" : "/api/proxy";

async function smartFetch(endpoint, options = {}) {
    // ยิงเข้าหา Internal Proxy (/api/proxy) เสมอเพื่อแก้ปัญหา CORS และ HTTPS
    const fullProxyUrl = endpoint.includes('http') ? endpoint : (endpoint.startsWith('?') ? `${BOT_API}${endpoint}` : BOT_API);

    try {
        const response = await fetch(fullProxyUrl, options);
        if (!response.ok) {
            console.error(`[SmartFetch] Failed: ${response.status}`);
        }
        return response;
    } catch (e) {
        console.error("[SmartFetch] Critical error:", e);
        throw e;
    }
}

// ==========================================
// GLOBALS
// ==========================================
let selectedGuildId = null;
let currentUserId = null;
let statusInterval = null;
let currentLang = 'EN';
// REALTIME STATE
let wsConnection = null;
let isRealtime = false;

let playerState = {
    position: 0,
    duration: 1,
    paused: true,
    lastUpdate: Date.now()
};

// ==========================================
// 1. CORE WRAPPERS (Matching HTML onclicks)
// ==========================================


// ==========================================
// 1. CORE WRAPPERS (Instant Polish)
// ==========================================

function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeJsStr(unsafe) {
    if (!unsafe) return '';
    return unsafe.toString().replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r');
}

function control(action, value = null) {
    if (!selectedGuildId) {
        showNotification("No Channel", "ไม่ระบุช่อง", "Please join a voice channel first to control the player.", "กรุณาเข้าห้องเสียงก่อนเพื่อควบคุมเครื่องเล่นนะครับ", "error");
        return;
    }

    // OPTIMISTIC UPDATE: Update UI immediately explicitly
    if (action === 'playpause') {
        const playIcon = document.getElementById('play-icon');
        const isPaused = playerState.paused;
        // Toggle state locally first
        playerState.paused = !isPaused;
        if (playIcon) playIcon.className = playerState.paused ? 'fas fa-play' : 'fas fa-pause';

        // Resume/Pause timer logic
        if (!playerState.paused) {
            playerState.lastUpdate = performance.now();
        }
    }
    else if (action === 'stop') {
        updatePlayerUI({ is_playing: false });
    }

    // Map actions
    let apiAction = action;
    if (action === 'playpause') apiAction = 'pause'; // API calls it 'pause' (toggle)
    else if (action === 'prev' || action === 'next') {
        apiAction = 'skip';
        // Optimistic: Reset progress to 0 on skip
        updateProgressUI(0, playerState.duration);
    }
    else if (action === 'volume') {
        handleVolume(value);
        return; // handleVolume calls sendControl
    }

    sendControl(apiAction, value);
}

/**
 * Seek track by clicking progress bar (Instant Feedback)
 */
function seekTrack(event) {
    if (!playerState.duration || playerState.duration <= 0) return;

    const bar = document.getElementById('progress-bar');
    if (!bar) return;

    const rect = bar.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const width = rect.width;
    const percent = Math.max(0, Math.min(x / width, 1));
    const seekPos = Math.floor(percent * playerState.duration);

    // OPTIMISTIC: Update State & UI Immediately
    playerState.position = seekPos;
    playerState.lastUpdate = performance.now(); // Reset sync timer

    updateProgressUI(seekPos, playerState.duration); // Force draw

    // Send to bot
    console.log(`[Dashboard] Seeking to: ${seekPos}ms`);
    sendControl('seek', seekPos);
}

// ==========================================
// 2. INTERNAL LOGIC (High Precision)
// ==========================================

// Start local timer for smooth updates
function startLocalTimer() {
    updateLocalTimer();
    requestAnimationFrame(startLocalTimer);
}
requestAnimationFrame(startLocalTimer);

function updateLocalTimer() {
    if (!playerState.paused && playerState.duration > 0) {
        const now = performance.now(); // Use High Res Time
        // Fallback Initialize
        if (!playerState.lastUpdate) playerState.lastUpdate = now;

        const elapsed = now - playerState.lastUpdate;

        // Predict current position
        let estimatedPos = playerState.position + elapsed;

        // Cap at duration
        if (estimatedPos > playerState.duration) estimatedPos = playerState.duration;

        // Update UI only (Don't update state.position permanent to avoid drift accumulation)
        updateProgressUI(estimatedPos, playerState.duration);
    }
}

function updateProgressUI(currentMs, totalMs) {
    const progressBar = document.getElementById('progress-fill');
    const timeCurrent = document.getElementById('current-time');
    const timeTotal = document.getElementById('total-duration');
    const isStream = window.currentTrack && window.currentTrack.is_stream;

    let percent = 0;
    if (isStream) {
        percent = 100; // Full bar for streams
        if (timeCurrent) timeCurrent.textContent = formatTime(currentMs);
        if (timeTotal) timeTotal.textContent = "LIVE";
    } else {
        if (totalMs > 0) {
            percent = Math.min((currentMs / totalMs) * 100, 100);
        }
        if (timeCurrent) timeCurrent.textContent = formatTime(currentMs);
        if (timeTotal) timeTotal.textContent = formatTime(totalMs);
    }

    if (progressBar) {
        progressBar.style.width = `${percent}%`;
        if (isStream) progressBar.classList.add('stream-progress');
        else progressBar.classList.remove('stream-progress');
    }
}

function formatTime(ms) {
    if (ms >= 360000000) return "LIVE"; // 100 hours+ or infinity
    if (!ms || isNaN(ms) || ms < 0) return "0:00";

    const totalSeconds = Math.floor(ms / 1000);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;

    if (h > 0) {
        return `${h}:${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`;
    }
    return `${m}:${s < 10 ? '0' + s : s}`;
}

// ==========================================
// 3. AUTH & CONNECTION
// ==========================================

let isAutoConnecting = false; // Guard: prevent duplicate auto-connect calls

function onUserLoggedIn(user) {
    if (!user) return;

    currentUserId = user.id;

    // Dynamic Page Title
    document.title = `${user.username}'s Dashboard - Cyori`;

    showDashboard();

    const nameEl = document.getElementById('user-name');
    const avatarEl = document.getElementById('user-avatar');
    const discEl = document.getElementById('user-discriminator');

    if (nameEl) {
        // Safe update: Remove text nodes but keep elements (like badges/spans)
        // Then prepend the new username text

        // 1. Filter out existing text nodes to clear "Loading..."
        Array.from(nameEl.childNodes).forEach(node => {
            if (node.nodeType === 3) { // Text node
                node.remove();
            }
        });

        // 2. Insert new text at the beginning
        nameEl.prepend(document.createTextNode(user.username));
    }
    if (discEl) discEl.textContent = user.discriminator ? `#${user.discriminator}` : "";
    if (avatarEl) {
        const avatarUrl = user.avatar
            ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
            : `https://cdn.discordapp.com/embed/avatars/${parseInt(user.id) % 5}.png`;
        avatarEl.src = avatarUrl;
    }

    // GUARD: Only run auto-connect once (onUserLoggedIn can be called multiple times)
    if (!isAutoConnecting) {
        isAutoConnecting = true;
        startAutoConnect(user.id);
    }

    // Init Favorites & Recommendations (idempotent — safe to call multiple times)
    setTimeout(() => {
        renderCollection();
        fetchRecommendations();
    }, 500);
}

function switchTab(tabId, btn) {
    // 1. Hide all tabs
    const tabs = document.querySelectorAll('.dash-tab-content');
    tabs.forEach(t => t.style.display = 'none');

    // 2. Show target tab
    const target = document.getElementById(`tab-${tabId}`);
    if (target) {
        target.style.display = tabId === 'player' ? 'block' : 'block'; // Ensure block display
        if (tabId === 'favorites') renderCollection();
        if (tabId === 'lyrics') fetchLyrics();

        // Dynamic Player Main Styling for YouTube layout
        const playerMain = document.querySelector('.player-main');
        if (playerMain) {
            if (tabId === 'player') {
                playerMain.style.background = 'transparent';
                playerMain.style.border = 'none';
                playerMain.style.padding = '0';
                playerMain.style.boxShadow = 'none';
            } else {
                playerMain.style.background = 'var(--bg-card)';
                playerMain.style.border = '1px solid var(--glass-border)';
                playerMain.style.padding = '40px';
            }
        }
    }

    // 3. Update sidebar buttons
    const btns = document.querySelectorAll('.sidebar-btn');
    btns.forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
}

// 7. COLLECTION / PLAYLISTS (Consolidated at end)
// ==========================================
// 8. RECOMMENDED CLIPS
// ==========================================

async function fetchRecommendations() {
    const list = document.getElementById('recommended-list');
    if (!list || !window.accessToken) return;

    // Use currentUserId instead of window.userId
    const userId = typeof currentUserId !== 'undefined' ? currentUserId : '';

    // Use a small delay if called during init to ensure selectedGuildId is settled
    if (!selectedGuildId) {
        // Fallback: Still fetch trending if no guild selected, but don't spam
        console.log("[Recommended] No guild selected, fetching trending...");
    }

    try {
        const res = await smartFetch(`?action=recommended&guild_id=${selectedGuildId || ''}&user_id=${userId}`);

        if (!res.ok) {
            const errBody = await res.text();
            console.warn(`[Recommended] API Error ${res.status}:`, errBody);
            // Don't show error to user, just hide if failed
            list.innerHTML = `<p class="lang-text" data-en="No recommendations yet. Start playing music!" data-th="ยังไม่มีเพลงแนะนำ เริ่มฟังเพลงเพื่อให้เราแนะนำได้แม่นยำขึ้น!"></p>`;
            updateLanguage();
            return;
        }

        const data = await res.json();
        if (data.results && data.results.length > 0) {
            renderRecommendations(data.results);
        } else {
            list.innerHTML = `<p class="lang-text" data-en="No recommendations yet. Start playing music!" data-th="ยังไม่มีเพลงแนะนำ เริ่มฟังเพลงเพื่อให้เราแนะนำได้แม่นยำขึ้น!"></p>`;
            updateLanguage();
        }
    } catch (e) {
        console.error("[Recommended] Fetch failed:", e);
    }
}

function renderRecommendations(tracks) {
    const list = document.getElementById('recommended-list');
    if (!list) return;

    // Render as a vertical list to match the YouTube sidebar feeling
    list.innerHTML = tracks.map(track => {
        const safeEncoded = escapeJsStr(track.encoded || "");
        const safeUri = escapeJsStr(track.uri || "");
        const safeTitleHtml = escapeHtml(track.title);
        const safeAuthorHtml = escapeHtml(track.author);
        const safeThumb = escapeHtml(track.thumbnail);

        return `
        <div class="queue-item" onclick="playTrack('${safeEncoded}', '${safeUri}')" style="cursor: pointer; padding: 6px 10px; border: none; border-radius: 12px; background: transparent; display: flex; align-items: center; gap: 12px;">
            <div class="qi-thumb" style="position: relative; width: 64px; height: 48px; border-radius: 8px; flex-shrink: 0; background: #000; overflow: hidden; border: 1px solid rgba(255,255,255,0.05);">
                <img src="${safeThumb}" onerror="this.src='logo-circle.png'" style="width: 100%; height: 100%; object-fit: cover;">
                <div style="position: absolute; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; opacity: 0; transition: 0.2s;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0">
                    <i class="fas fa-play" style="font-size: 0.9rem; color: #fff;"></i>
                </div>
            </div>
            <div class="qi-info" style="flex: 1; min-width: 0;">
                <div class="qi-title" style="font-size: 0.9rem; font-weight: 600; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.2; margin-bottom: 4px;" title="${safeTitleHtml}">${safeTitleHtml}</div>
                <div class="qi-artist" style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${safeAuthorHtml}</div>
            </div>
        </div>
        `;
    }).join('');
}

async function playFavorite(encoded, uri) {
    if (!selectedGuildId) {
        alert("Please join a voice channel first / กรุณาเข้าห้องเสียงก่อน");
        return;
    }

    // Construct Payload for Play
    // Note: If encoded is empty string, backend logic should fallback to URI
    const payload = JSON.stringify({
        encoded: encoded,
        uri: uri,
        source: 'favorite'
    });

    // Optimistic UI Feedback
    showNotification("Adding to Queue", "กำลังเพิ่มลงคิว", "Song added from collection.", "เพิ่มเพลงจากคอลเลกชันแล้ว", "success");

    await sendControl('play', { encoded, uri, source: 'favorite' });
}

function showDashboard() {
    const loginWall = document.getElementById('login-wall');
    const dashboardContainer = document.getElementById('dashboard-container');
    const ytSearch = document.getElementById('yt-search-container');

    if (loginWall) loginWall.style.display = 'none';
    if (dashboardContainer) dashboardContainer.style.display = 'block';
    if (ytSearch) ytSearch.style.display = 'flex'; // Use flex for the search container
}

function startAutoConnect(userId) {
    autoConnectVoice(userId);
}

async function autoConnectVoice(userId) {
    try {
        console.log("Searching for user voice channel...");
        const res = await smartFetch(`?action=find_voice&user_id=${userId}`);
        const data = await res.json();

        if (data.found && data.guild_id) {
            console.log(`Found user in: ${data.guild_name}`);
            selectServer(data.guild_id);
        } else {
            console.warn("User not found in any voice channel.");
        }
    } catch (e) {
        console.error("Auto-connect Error:", e);
    }
}

function selectServer(guildId) {
    selectedGuildId = guildId;
    fetchStatus();
    fetchRecommendations(); // Refresh recommendations for this guild

    // Start Realtime Engine
    initRealtime(guildId);
}

// =========================================
// REALTIME ENGINE (ZERO DELAY)
// =========================================
function initRealtime(guildId) {
    // GUARD: Avoid redundant connections (OPEN or mid-handshake CONNECTING)
    if (wsConnection &&
        (wsConnection.readyState === WebSocket.OPEN ||
            wsConnection.readyState === WebSocket.CONNECTING)) {
        return; // Already connected or connecting — do not create a new socket
    }

    if (wsConnection) {
        try { wsConnection.close(); } catch (e) { }
    }

    // Determine WS URL (Smart Direct Logic)
    let wsUrl = '';

    // 1. LOCAL ENVIRONMENT (Direct Connect)
    if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
        wsUrl = `ws://${location.hostname}:8000/api/gateway`;
    }
    // 2. PRODUCTION (Proxy through Cloudflare Pages Function)
    else {
        // Use the same domain as frontend to avoid Mixed Content (HTTPS -> WSS)
        // The /api/gateway function will proxy this to the backend
        const protocol = location.protocol === 'https:' ? 'wss://' : 'ws://';
        wsUrl = `${protocol}${location.host}/api/gateway`;
    }

    // console.log("[Realtime] Connecting:", wsUrl);

    try {
        wsConnection = new WebSocket(wsUrl);

        wsConnection.onopen = () => {
            console.log("[Realtime] Connected!");
            isRealtime = true;
            if (statusInterval) clearInterval(statusInterval);

            wsConnection.send(JSON.stringify({
                op: 'connect',
                guild_id: guildId
            }));
        };

        wsConnection.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.op === 'state') {
                    const d = msg.data;
                    updatePlayerUI({
                        is_playing: d.playing,
                        paused: d.paused,
                        position: d.pos,
                        duration: d.duration,
                        title: d.title || 'Nothing Playing',
                        author: d.author || '-',
                        thumbnail: d.thumbnail,
                        encoded: d.encoded || '',
                        uri: d.uri || '',
                        volume: d.vol || 100,
                        is_stream: d.is_stream || false,
                        loop_mode: d.loop_mode || "off",
                        queue: d.queue || []
                    });
                }
            } catch (x) {
                console.error("[Realtime] Message Error:", x);
            }
        };

        wsConnection.onclose = () => {
            isRealtime = false;
            startFallbackPolling();
        };

    } catch (e) {
        startFallbackPolling();
    }
}

function startFallbackPolling() {
    if (statusInterval) clearInterval(statusInterval);
    statusInterval = setInterval(fetchStatus, 3000);
}

async function fetchStatus() {
    if (!selectedGuildId) return;

    // OPTIMIZATION: Don't fetch if tab is hidden (saves bandwidth and Worker requests)
    if (document.hidden) {
        // console.log("[Dashboard] Tab hidden, skipping update...");
        return;
    }

    try {
        const res = await smartFetch(`?action=status&guild_id=${selectedGuildId}`);
        const d = await res.json();
        if (!d.error) updatePlayerUI({
            is_playing: d.playing,
            paused: d.paused,
            position: d.pos,
            duration: d.duration,
            title: d.title || 'Nothing Playing',
            author: d.author || '-',
            thumbnail: d.thumbnail,
            encoded: d.encoded || '',
            uri: d.uri || '',
            volume: d.vol || 100,
            is_stream: d.is_stream || false,
            loop_mode: d.loop_mode || 'off',
            queue: d.queue || []
        });
    } catch (e) {
        console.error("Fetch Status Error:", e);
    }
}

let isRequesting = false; // Guard for overlapping requests

async function playRandom() {
    if (!selectedGuildId) {
        showNotification("No Channel", "ไม่ระบุช่อง", "Please join a voice channel first.", "กรุณาเข้าห้องเสียงก่อนนะครับ", "error");
        return;
    }

    // UI Feedback
    const btn = event?.currentTarget;
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) icon.className = 'fas fa-dice fa-spin';
        setTimeout(() => { if (icon) icon.className = 'fas fa-dice'; }, 1000);
    }

    console.log("[Dashboard] Requesting random song...");
    await sendControl('random');
}

async function sendControl(action, value = null) {
    if (!selectedGuildId || isRequesting) return;

    // FORWARD CERTAIN ACTIONS TO HTTP (PLAY/SEARCH need backend logic)
    const alwaysHttp = ['play', 'search', 'skipto', 'proxy_control', 'random'];

    // REALTIME SOCKET SEND (Fastest for UI controls like pause/skip/volume)
    if (isRealtime && wsConnection && wsConnection.readyState === WebSocket.OPEN && !alwaysHttp.includes(action)) {
        wsConnection.send(JSON.stringify({
            op: 'control',
            guild_id: selectedGuildId,
            action: action,
            value: value
        }));
        return;
    }

    // Allow volume to bypass or handle separately? 
    // Let's keep it simple: everything gets a small cooldown.
    isRequesting = true;
    setTimeout(() => { isRequesting = false; }, 500); // 500ms cooldown

    // DE-DUPLICATION: Add unique event ID
    const eventId = `dash_${Date.now()}_${Math.floor(Math.random() * 1000)}`;

    try {
        const response = await smartFetch('', {
            method: 'POST',
            body: JSON.stringify({
                action: action,
                guild_id: selectedGuildId,
                user_id: currentUserId,
                value: value,
                event_id: eventId // Send ID for bot-side de-duplication
            })
        });

        const data = await response.json();

        // Show success message if returned (e.g. Loop Mode, Added to Favorites)
        if (data.status === 'ok' && data.message) {
            showNotification("Success", "สำเร็จ", data.message, data.message, "success");
        }

        if (data.error) {
            console.error(`[Control Error] ${data.error}`);
            if (data.error.includes("ไม่รองรับ") || data.error.includes("not supported")) {
                showNotification(
                    "Source Not Supported",
                    "ไม่รองรับแหล่งที่มานี้",
                    "This music source is not supported by our player. Please try another link.",
                    "ขออภัย ระบบไม่รองรับการเล่นเพลงจากแหล่งที่มานี้ โปรดลองใช้ลิงก์จากแหล่งอื่นแทน"
                );
            } else {
                showNotification("Error", "เกิดข้อผิดพลาด", data.error, data.error);
            }
        }

        // Trigger immediate refresh after action
        setTimeout(fetchStatus, 800);
    } catch (e) {
        console.error("Control Error:", e);
    }
}

function showNotification(titleEn, titleTh, msgEn, msgTh, type = "error") {
    const modal = document.getElementById('notification-modal');
    const titleEl = document.getElementById('notify-title');
    const msgEl = document.getElementById('notify-message');
    const iconEl = document.getElementById('notify-icon');

    if (!modal || !titleEl || !msgEl) return;

    // Detect language from button if not stored
    const langBtn = document.getElementById('curr-lang');
    const lang = langBtn ? langBtn.textContent.trim().toUpperCase() : 'EN';

    titleEl.textContent = lang === 'TH' ? titleTh : titleEn;
    msgEl.innerHTML = lang === 'TH' ? msgTh.replace(/\n/g, '<br>') : msgEn.replace(/\n/g, '<br>');

    // Style based on type
    if (type === "error") {
        titleEl.style.color = "#FF4444";
        iconEl.style.color = "#FF4444";
        iconEl.innerHTML = '<i class="fas fa-exclamation-circle"></i>';
    } else {
        titleEl.style.color = "var(--gold-primary)";
        iconEl.style.color = "var(--gold-primary)";
        iconEl.innerHTML = '<i class="fas fa-info-circle"></i>';
    }

    modal.style.display = 'flex';
}

function handleVolume(value) {
    const icon = document.querySelector('.volume-control i');
    if (icon) {
        if (value == 0) icon.className = 'fas fa-volume-mute';
        else if (value < 50) icon.className = 'fas fa-volume-down';
        else icon.className = 'fas fa-volume-up';
    }
    // API Call
    sendControl('volume', value);
}

// ==========================================
// 4. PLAYER UI UPDATE
// ==========================================

function updatePlayerUI(data) {
    if (!data) return;


    const img = document.getElementById('np-art');
    const title = document.getElementById('np-title');
    const artist = document.getElementById('np-artist');
    const playIcon = document.getElementById('play-icon');
    const btnShuffle = document.getElementById('btn-shuffle');
    const btnLoop = document.getElementById('btn-loop');

    const isPlaying = data.is_playing;

    if (!isPlaying) {
        if (title) title.textContent = "No music playing";
        if (artist) artist.textContent = "Ready to play";
        if (img) {
            img.src = "logo-circle.png";
        }
        if (playIcon) playIcon.className = 'fas fa-play';
        updateProgressUI(0, 0); // Reset to 0:00 / 0:00
        playerState.paused = true;
        playerState.position = 0;
        playerState.duration = 0;
        window.currentTrack = null;
        if (btnShuffle) btnShuffle.classList.remove('active');
        if (btnLoop) btnLoop.classList.remove('active');

        // Reset favorite button
        const favIcon = document.querySelector('#btn-favorite i');
        if (favIcon) {
            favIcon.className = 'far fa-heart';
            favIcon.style.color = '';
        }

        renderQueue([]); // Clear queue list
        return;
    }

    // Ensure we have current track data for Favorites feature
    window.currentTrack = {
        title: data.title,
        author: data.author,
        uri: data.uri || data.web_url,
        thumbnail: data.thumbnail,
        length: data.duration,
        is_stream: data.is_stream || false,
        encoded: data.encoded
    };

    // Toggle Live Badge
    const liveBadge = document.querySelector('.live-badge');
    if (liveBadge) liveBadge.style.display = data.is_stream ? 'block' : 'none';

    // Update Meta
    if (title) title.textContent = data.title || "Unknown Title";
    if (artist) artist.textContent = data.author || "Unknown Artist";
    if (img && data.thumbnail) {
        img.src = data.thumbnail.includes('null') ? "logo-circle.png" : data.thumbnail;
    }

    // Update Icons
    if (playIcon) playIcon.className = data.paused ? 'fas fa-play' : 'fas fa-pause';

    if (btnShuffle) {
        data.shuffle ? btnShuffle.classList.add('active') : btnShuffle.classList.remove('active');
    }

    if (btnLoop) {
        const loopMode = (data.loop_mode || "off").toLowerCase();
        const loopTextEl = document.getElementById('loop-text');
        if (loopMode !== "off") {
            btnLoop.classList.add('active');
            btnLoop.querySelector('i').className = (loopMode === 'track' || loopMode === 'song') ? 'fas fa-redo-alt' : 'fas fa-redo';
            // Update displayed text
            if (loopTextEl) {
                if (loopMode === 'track' || loopMode === 'song') {
                    loopTextEl.textContent = loopTextEl.dataset.en === 'Off' ? 'Track' : 'Track'; // fallback
                    // Use language-specific text if needed
                    if (loopTextEl.dataset.en) loopTextEl.dataset.en = 'Track';
                    if (loopTextEl.dataset.th) loopTextEl.dataset.th = 'เพลง';
                } else {
                    loopTextEl.textContent = 'Queue';
                    if (loopTextEl.dataset.en) loopTextEl.dataset.en = 'Queue';
                    if (loopTextEl.dataset.th) loopTextEl.dataset.th = 'คิว';
                }
            }
        } else {
            btnLoop.classList.remove('active');
            btnLoop.querySelector('i').className = 'fas fa-redo';
            if (loopTextEl) {
                loopTextEl.textContent = 'Off';
                if (loopTextEl.dataset.en) loopTextEl.dataset.en = 'Off';
                if (loopTextEl.dataset.th) loopTextEl.dataset.th = 'ปิด';
            }
        }
    }

    // Update Progress Data
    playerState.position = data.position || 0;
    playerState.duration = data.duration || 1;
    playerState.paused = data.paused;
    playerState.lastUpdate = performance.now(); // MUST use performance.now() to match timer

    updateProgressUI(playerState.position, playerState.duration);

    // Update Favorite Icon Color
    // Update Favorite Icon Color
    updateFavoriteButton();

    if (data.queue) renderQueue(data.queue);

    // Auto-update lyrics if tab is visible and song changed
    const lyricsTab = document.getElementById('tab-lyrics');
    if (lyricsTab && lyricsTab.style.display !== 'none') {
        fetchLyrics();
    }
}

// ==========================================
// 5. SEARCH & QUEUE
// ==========================================

function renderSearchResultsToModal(tracks) {
    const container = document.getElementById('modal-results-list');
    if (!container) return;

    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div style="padding:20px; color:#aaa; text-align:center;">No results found</div>';
        return;
    }

    container.innerHTML = tracks.map(track => {
        let icon = '<i class="fas fa-music"></i>';
        const uri = track.uri || "";
        if (uri.includes('youtube') || uri.includes('youtu.be')) icon = '<i class="fab fa-youtube" style="color:#ff0000"></i>';
        else if (uri.includes('spotify')) icon = '<i class="fab fa-spotify" style="color:#1db954"></i>';

        const safeUriJs = escapeJsStr(uri);
        const safeEncodedJs = escapeJsStr(track.encoded);
        const safeTitleJs = escapeJsStr(track.title);
        const safeTitleHtml = escapeHtml(track.title);
        const safeAuthorHtml = escapeHtml(track.author);

        return `
            <div class="search-result-item" style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 12px; background: rgba(255,255,255,0.03); margin-bottom: 8px; transition: 0.2s;">
                <div class="result-icon" onclick="playTrack('${safeEncodedJs}', '${safeUriJs}')" style="cursor: pointer;">${icon}</div>
                <div class="result-info" onclick="playTrack('${safeEncodedJs}', '${safeUriJs}')" style="flex: 1; cursor: pointer;">
                    <span class="result-title" style="display: block; font-weight: 500;">${safeTitleHtml}</span>
                    <span class="result-author" style="font-size: 0.8rem; color: var(--text-muted);">${safeAuthorHtml} • ${formatTime(track.length)}</span>
                </div>
                <div class="result-actions" style="display: flex; gap: 10px;">
                    <button class="btn-glass" onclick="showAddToPlaylistModal('${safeEncodedJs}', '${safeUriJs}', '${safeTitleJs}')" 
                            style="width: 32px; height: 32px; border-radius: 50%; padding: 0; font-size: 0.8rem;" title="Add to Playlist">
                        <i class="fas fa-plus"></i>
                    </button>
                    <div onclick="playTrack('${safeEncodedJs}', '${safeUriJs}')" style="cursor: pointer; color: var(--gold-primary); font-size: 1.2rem;">
                        <i class="fas fa-play-circle"></i>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function performSearch() {
    const input = document.getElementById('song-input');
    const query = input.value.trim();
    if (!query) return;

    if (!selectedGuildId) {
        alert("Please join a voice channel first!");
        return;
    }

    // URL Detection
    const isUrl = /^(http|https):\/\/[^ "]+$/.test(query);
    if (isUrl) {
        await playTrack(null, query);
        input.value = '';
        return;
    }

    // Loading State
    const searchBtn = document.querySelector('.search-box-wrapper .btn-primary');
    const origIcon = searchBtn ? searchBtn.innerHTML : '';
    if (searchBtn) searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    try {
        const res = await smartFetch(`?action=search&query=${encodeURIComponent(query)}&guild_id=${selectedGuildId}`);
        const data = await res.json();

        if (data.results && data.results.length > 0) {
            // If we have a modal, show results there.
            if (document.getElementById('search-modal')) {
                renderSearchResultsToModal(data.results);
                document.getElementById('search-modal').style.display = 'flex';
            } else {
                const first = data.results[0];
                playTrack(first.encoded, first.uri);
            }
        } else if (data.error) {
            showNotification(
                "Source Not Supported",
                "ไม่รองรับแหล่งที่มานี้",
                "This music source is not supported or nothing was found.",
                "ไม่รองรับแหล่งที่มานี้ หรือไม่พบข้อมูลเพลงที่ต้องการ"
            );
        } else {
            showNotification("No Results", "ไม่พบผลลัพธ์", "No results found for your query.", "ไม่พบผลลัพธ์สำหรับคำค้นหานี้");
        }
    } catch (e) {
        console.error("Search Error:", e);
        showNotification("Search Error", "ข้อผิดพลาดการค้นหา", "Failed to perform search. Please try again.", "การค้นหาล้มเหลว โปรดลองอีกครั้ง");
    } finally {
        if (searchBtn) searchBtn.innerHTML = origIcon;
    }
}

async function playTrack(encoded, uri) {
    const modal = document.getElementById('search-modal');
    if (modal) modal.style.display = 'none';

    const input = document.getElementById('song-input');
    if (input) input.value = '';

    // UI Feedback: Show loading on the card if possible or global notification
    console.log(`[Dashboard] Playing track: ${encoded || uri}`);

    await sendControl('play', { encoded, uri, source: 'dashboard' });
}

// --- Add to Playlist Feature ---
let trackToAddToPlaylist = null;

function showAddToPlaylistModal(encoded, uri, title) {
    trackToAddToPlaylist = { encoded, uri, title };
    const modal = document.getElementById('add-to-playlist-modal');
    if (!modal) {
        // Fallback for first time creating modal
        createAddToPlaylistModal();
        return;
    }
    renderPlaylistOptions();
    modal.style.display = 'flex';
}

function createAddToPlaylistModal() {
    const html = `
    <div id="add-to-playlist-modal" class="modal" style="display: flex;">
        <div class="modal-content glass-effect" style="max-width: 400px;">
            <div class="modal-header">
                <h3 class="lang-text" data-en="Add to Playlist" data-th="เพิ่มลงเพลย์ลิสต์">Add to Playlist</h3>
                <button class="close-btn" onclick="document.getElementById('add-to-playlist-modal').style.display='none'">&times;</button>
            </div>
            <div class="modal-body" style="padding: 20px;">
                <p id="attp-track-name" style="font-size: 0.9rem; margin-bottom: 20px; color: var(--gold-primary); font-weight: 600;"></p>
                <div id="playlist-options-list" style="max-height: 250px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px;">
                    <!-- Playlists here -->
                </div>
            </div>
        </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    renderPlaylistOptions();
}

function renderPlaylistOptions() {
    const container = document.getElementById('playlist-options-list');
    const trackNameTip = document.getElementById('attp-track-name');
    if (!container || !trackToAddToPlaylist) return;

    trackNameTip.textContent = trackToAddToPlaylist.title;

    // Use userPlaylists from Collection system if available
    const playlists = (typeof userPlaylists !== 'undefined' && userPlaylists.length > 0) ? userPlaylists : [];

    let html = '';

    // Add "Create New" option at top
    html += `
        <button class="btn-primary" onclick="createNewPlaylistPrompt()" 
                style="width: 100%; text-align: center; padding: 12px; border-radius: 12px; margin-bottom: 10px; font-weight: 600;">
            <i class="fas fa-plus"></i> Create New Playlist
        </button>
    `;

    if (playlists.length === 0) {
        html += `<p style="text-align: center; color: #aaa; padding: 20px;">No playlists found.</p>`;
    } else {
        html += playlists.map((pl, idx) => `
            <button class="btn-glass" onclick="confirmAddTrackToPlaylist(${idx})" 
                    style="width: 100%; text-align: left; padding: 12px 15px; border-radius: 12px; display: flex; flex-direction: column; gap: 4px; transition: 0.2s;">
                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                    <span style="font-weight: 600;">${pl.name}</span>
                    <i class="fas fa-plus-circle" style="color: var(--gold-primary);"></i>
                </div>
                <div style="font-size: 0.7rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${pl.description || 'No description'}
                </div>
            </button>
        `).join('');
    }

    container.innerHTML = html;
}

async function createNewPlaylistPrompt() {
    const name = prompt("ชื่อเพลย์ลิสต์ใหม่ (New Playlist Name):");
    if (!name) return;
    const desc = prompt("คำอธิบาย (Description):", "คอลเลกชันเพลงใหม่ของฉัน");

    try {
        const res = await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({
                user_id: currentUserId,
                action: 'create',
                name: name,
                description: desc
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            await renderCollection(); // Refresh global list
            renderPlaylistOptions(); // Refresh current modal
        }
    } catch (e) {
        console.error(e);
    }
}

async function confirmAddTrackToPlaylist(plIdx) {
    if (!trackToAddToPlaylist) return;

    try {
        const res = await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({
                user_id: currentUserId,
                action: 'add_track',
                playlist_index: plIdx,
                track: trackToAddToPlaylist
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            document.getElementById('add-to-playlist-modal').style.display = 'none';
            showNotification("Added", "เพิ่มแล้ว", "Track added to playlist.", "เพิ่มเพลงลงเพลย์ลิสต์เรียบร้อยแล้ว", "success");
            if (typeof window.fetchPremiumStatus === 'function') await window.fetchPremiumStatus(); // Sync
        }
    } catch (e) {
        console.error(e);
    }
}


// ==========================================
// 6. INITIALIZATION & EVENTS
// ==========================================

async function playTrack(encoded, uri) {
    if (!selectedGuildId) return showNotification("No Channel", "ไม่ระบุช่อง", "Please join a voice channel first.", "กรุณาเข้าห้องเสียงก่อนนะครับ", "error");
    await sendControl('play', { encoded, uri, source: 'dashboard' });
}

function attachSeekListener() {
    const bar = document.getElementById('progress-bar');
    if (bar && !bar.hasAttribute('data-listening')) {
        bar.addEventListener('click', seekTrack);
        bar.setAttribute('data-listening', 'true');
    }
}

// Ensure listener is attached after UI updates
const originalUpdatePlayerUI = updatePlayerUI;
updatePlayerUI = function (data) {
    if (typeof originalUpdatePlayerUI === 'function') originalUpdatePlayerUI(data);
    attachSeekListener();
};

function renderQueue(queue) {
    const list = document.getElementById('queue-list');
    if (!list) return;

    if (!queue || queue.length === 0) {
        list.innerHTML = '<div class="queue-empty">Queue is empty</div>';
        return;
    }

    list.innerHTML = queue.map((track, index) => {
        const safeTitleHtml = escapeHtml(track.title || "Unknown");
        const safeAuthorHtml = escapeHtml(track.author || "Unknown");
        const safeThumb = escapeHtml(track.thumbnail || 'logo-circle.png');

        // Format duration
        const duration = formatTime(track.duration || track.length);

        return `
        <div class="queue-item">
            <div class="qi-thumb">
                <img src="${safeThumb}" onerror="this.src='logo-circle.png'">
            </div>
            <div class="qi-info">
                <div class="qi-title" onclick="sendControl('skipto', ${index})">${safeTitleHtml}</div>
                <div class="qi-artist">${safeAuthorHtml} • ${duration}</div>
            </div>
            <div class="qi-actions">
                <button class="btn-glass btn-sm" onclick="sendControl('skipto', ${index})" title="Play Now"><i class="fas fa-play"></i></button>
                <button class="btn-glass btn-sm" onclick="sendControl('remove', ${index})" title="Remove"><i class="fas fa-trash"></i></button>
            </div>
        </div>
        `;
    }).join('');
}

// ==========================================
// 8. LYRICS FEATURE
// ==========================================

async function fetchLyrics(force = false) {
    const titleEl = document.getElementById('lyrics-title');
    const artistEl = document.getElementById('lyrics-artist');
    const textEl = document.getElementById('lyrics-text');
    const loadingEl = document.getElementById('lyrics-loading');

    if (!titleEl || !textEl) return;

    if (!window.currentTrack) {
        // Nothing playing
        titleEl.textContent = "No Song Playing";
        artistEl.textContent = "-";
        textEl.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); padding-top: 100px;">
                <i class="fas fa-music" style="font-size: 4rem; margin-bottom: 20px; opacity: 0.3;"></i>
                <p>Play a song to see lyrics</p>
            </div>`;
        return;
    }

    // Check if we already have lyrics for this track to avoid re-fetching
    // Check if we already have lyrics for this track to avoid re-fetching
    const currentSignature = `${window.currentTrack.title}-${window.currentTrack.author}`;
    // Use a simpler check for loaded content
    if (!force && window.lastLyricsSignature === currentSignature && textEl.innerText.length > 50 && !textEl.innerText.includes("Lyrics not found")) {
        return;
    }

    // Update UI
    titleEl.textContent = window.currentTrack.title || "Unknown Title";
    artistEl.textContent = window.currentTrack.author || "Unknown Artist";
    if (loadingEl) loadingEl.style.display = 'flex';
    textEl.innerHTML = ''; // Clear previous lyrics while loading

    try {
        const t = window.currentTrack.title || "";
        const a = window.currentTrack.author || "";
        const query = `${a} - ${t}`.trim();

        const res = await smartFetch(`?action=lyrics&query=${encodeURIComponent(query)}&guild_id=${selectedGuildId || ''}`);
        const data = await res.json();

        if (loadingEl) loadingEl.style.display = 'none';

        if (data.lyrics) {
            textEl.textContent = data.lyrics;
            window.lastLyricsSignature = currentSignature;
        } else {
            textEl.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); padding-top: 50px;">
                <i class="fas fa-align-slash" style="font-size: 3rem; margin-bottom: 20px; opacity: 0.3;"></i>
                <p>Lyrics not found for this song.</p>
            </div>`;
        }
    } catch (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        console.error("Lyrics Fetch Error:", e);
        textEl.textContent = "Failed to load lyrics. Please try again.";
    }
}


// Helper to update favorite button state based on current track
function updateFavoriteButton() {
    const favIcon = document.querySelector('#btn-favorite i');
    if (!favIcon || !window.currentTrack) return;

    const favorites = window.userFavorites || (window.userPremium && window.userPremium.favorites) || [];
    const currentUri = window.currentTrack.uri;
    const currentEncoded = window.currentTrack.encoded;

    const isFav = favorites.some(f =>
        (f.uri && currentUri && f.uri === currentUri) ||
        (f.encoded && currentEncoded && f.encoded === currentEncoded)
    );

    if (isFav) {
        favIcon.className = 'fas fa-heart';
        favIcon.style.color = '#ff5555'; // Red color
    } else {
        favIcon.className = 'far fa-heart';
        favIcon.style.color = ''; // Default
    }
}

async function addToFavorite() {
    if (!window.currentTrack) {
        showNotification("No Music", "ไม่มีเพลง", "No music is playing right now.", "ขณะนี้ไม่มีเพลงที่กำลังเล่นอยู่", "error");
        return;
    }

    // 1. Optimistic Update (Toggle Local State)
    const favorites = window.userFavorites || [];
    const currentUri = window.currentTrack.uri;
    const currentEncoded = window.currentTrack.encoded;

    const existingIndex = favorites.findIndex(f =>
        (f.uri && currentUri && f.uri === currentUri) ||
        (f.encoded && currentEncoded && f.encoded === currentEncoded)
    );

    let actionName = "Add";

    if (existingIndex > -1) {
        // REMOVE
        favorites.splice(existingIndex, 1);
        actionName = "Remove";
        showNotification("Removed from Favorites", "ลบแล้ว", "Removed from your collection.", "ลบเพลงออกจากคอลเลคชันแล้ว", "success");
    } else {
        // ADD
        // Create full track object locally
        const newFav = { ...window.currentTrack, added_at: Math.floor(Date.now() / 1000) };
        favorites.push(newFav);
        actionName = "Add";
        showNotification("Added to Favorites", "เพิ่มแล้ว", "Saved to your collection.", "บันทึกเพลงลงคอลเลคชันแล้ว", "success");
    }

    // Update Global State references
    window.userFavorites = favorites;
    if (window.userPremium) window.userPremium.favorites = favorites;

    // Refresh UI immediately
    updateFavoriteButton();

    // 2. Send to Backend
    await sendControl('favorite', window.currentTrack);

    // 3. Sync persistence in background
    setTimeout(renderCollection, 1000);
}

function handleQueueAction(action, index) {
    const item = document.getElementById(`q-item-${index}`);
    if (item) {
        item.style.opacity = '0.5';
        item.style.pointerEvents = 'none';
        if (action === 'remove') item.style.transform = 'scale(0.95)';
    }
    requestAnimationFrame(() => sendControl(action, index));
}

// 7. COLLECTION SYSTEM
// ==========================================
let userPlaylists = [];
let userFavorites = [];

async function renderCollection() {
    const listFav = document.getElementById('favorites-list');
    const listCustom = document.getElementById('custom-playlists-list');
    const limitInfo = document.getElementById('playlist-limit-info');

    if (!currentUserId) return;

    try {
        const resp = await smartFetch(`?action=user_info&user_id=${currentUserId}`);
        const data = await resp.json();

        userPlaylists = data.playlists || [];
        userFavorites = data.favorites || [];
        window.userFavorites = userFavorites; // Sync window reference
        const limit = data.playlist_limit || 20;

        // Sync local cache for script.js
        window.userPremium = data;
        localStorage.setItem('user_premium', JSON.stringify(data));

        // Update Sidebar Badge & Visual Status
        const badge = document.getElementById('user-badge');
        if (badge && data.plan) {
            badge.textContent = data.plan;
            if (data.is_owner || data.premium) {
                badge.className = "badge-premium lifetime"; // Add gold styling for admin/lifetime
            } else {
                badge.className = "badge-premium";
            }
        }

        if (limitInfo) limitInfo.textContent = `Playlists: ${userPlaylists.length} / ${limit}`;

        if (listFav) {
            listFav.innerHTML = userFavorites.length === 0
                ? `<div class="queue-empty" style="text-align:center; padding:20px; color:var(--text-muted);">No favorites yet</div>`
                : userFavorites.map((track) => {
                    const enc = track.encoded && track.encoded !== 'undefined' && track.encoded !== 'null' ? track.encoded : '';
                    const uri = track.uri || '';
                    const safeEnc = escapeJsStr(enc);
                    const safeUri = escapeJsStr(uri);
                    const safeTitle = escapeHtml(track.title);
                    const safeAuthor = escapeHtml(track.author);
                    const safeThumb = escapeHtml(track.thumbnail || 'logo-circle.png');
                    return `
                    <div class="queue-item" style="display: flex; align-items: center; gap: 10px; padding: 10px; background: rgba(255,255,255,0.05); margin-bottom: 5px; border-radius: 12px;">
                        <img src="${safeThumb}" style="width:40px; height:40px; border-radius:8px; object-fit: cover;" onerror="this.src='logo-circle.png'">
                        <div style="flex:1; overflow:hidden;">
                            <div style="font-weight:500; font-size:0.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${safeTitle}</div>
                            <div style="font-size:0.75rem; color:var(--text-muted);">${safeAuthor}</div>
                        </div>
                        <div style="display: flex; gap: 5px;">
                            <button class="btn-glass" onclick="playTrack('${safeEnc}', '${safeUri}')" style="width:30px; height:30px; padding:0;"><i class="fas fa-play" style="font-size:0.7rem;"></i></button>
                            <button class="btn-glass" onclick="removeFavorite('${safeUri}')" style="width:30px; height:30px; padding:0; color:#ff4d4d;"><i class="fas fa-trash" style="font-size:0.7rem;"></i></button>
                        </div>
                    </div>
                `}).join('');
        }

        if (listCustom) {
            listCustom.innerHTML = '';

            // Save Queue Card
            const saveCard = document.createElement('div');
            saveCard.className = 'card folder-card';
            saveCard.style.cssText = 'border: 2px dashed var(--glass-border); background: rgba(212, 175, 55, 0.05); cursor: pointer;';
            saveCard.onclick = saveQueuePrompt;
            saveCard.innerHTML = `
                <div style="text-align:center; padding: 25px 10px;">
                    <i class="fas fa-file-export" style="font-size:2.2rem; color:var(--gold-dim); margin-bottom:12px;"></i>
                    <div style="font-weight:700; font-size:1rem; color:var(--gold-primary);">Save Queue</div>
                    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:5px;">Save queue as playlist</div>
                </div>
            `;
            listCustom.appendChild(saveCard);

            userPlaylists.forEach((pl, idx) => {
                const thumb = (pl.tracks && pl.tracks.length > 0) ? pl.tracks[0].thumbnail : 'logo-circle.png';
                const el = document.createElement('div');
                el.className = 'card folder-card';
                el.innerHTML = `
                    <div class="folder-thumb-wrapper" onclick="viewPlaylist(${idx})">
                        <img src="${thumb}" class="folder-thumb">
                        <div class="folder-badge"><i class="fas fa-compact-disc fa-spin-slow"></i> ${pl.tracks ? pl.tracks.length : 0} tracks</div>
                        <div class="folder-play-overlay" onclick="event.stopPropagation(); playPlaylist(${idx})"><i class="fas fa-play-circle"></i></div>
                    </div>
                    <div class="folder-info">
                        <div class="folder-name">${pl.name}</div>
                        <div class="folder-actions">
                            <button class="btn-folder" onclick="viewPlaylist(${idx})" title="View"><i class="fas fa-list"></i></button>
                            <button class="btn-folder" onclick="deletePlaylist(${idx})" title="Delete" style="color:#ff6666;"><i class="fas fa-trash-alt"></i></button>
                        </div>
                    </div>
                `;
                listCustom.appendChild(el);
            });
        }
    } catch (e) {
        console.error("Collection Render Error:", e);
    }
}

async function saveQueueToPlaylist(name, description) {
    if (!selectedGuildId) return;
    try {
        const resp = await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({ user_id: currentUserId, guild_id: selectedGuildId, action: 'save_queue', name, description })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            showNotification("Success", "สำเร็จ", "Queue saved to playlist.", "บันทึกคิวเป็นเพลย์ลิสต์แล้ว", "success");
            renderCollection();
        }
    } catch (e) { console.error(e); }
}

function saveQueuePrompt() {
    const name = prompt("Playlist Name:", `Queue ${new Date().toLocaleDateString()}`);
    if (name) saveQueueToPlaylist(name, "");
}

function viewPlaylist(idx) {
    const pl = userPlaylists[idx];
    if (!pl) return;
    const modal = document.getElementById('search-modal');
    if (!modal) return;
    const title = modal.querySelector('.modal-header h3');
    const list = document.getElementById('modal-results-list');
    title.textContent = `Playlist: ${pl.name}`;
    list.innerHTML = (pl.tracks || []).map(t => {
        const safeEnc = escapeJsStr(t.encoded);
        const safeUri = escapeJsStr(t.uri);
        const safeTitle = escapeHtml(t.title);
        const safeAuthor = escapeHtml(t.author);
        const safeThumb = escapeHtml(t.thumbnail || 'logo-circle.png');
        return `
        <div class="search-result-item" style="display: flex; align-items: center; gap: 15px; padding: 10px; border-radius: 12px; background: rgba(255,255,255,0.03); margin-bottom: 5px;">
            <img src="${safeThumb}" style="width:50px; height:50px; border-radius:8px; object-fit: cover;" onerror="this.src='logo-circle.png'">
            <div style="flex:1; overflow:hidden;">
                <div style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${safeTitle}</div>
                <div style="font-size:0.8rem; color:var(--text-muted);">${safeAuthor}</div>
            </div>
            <button class="btn btn-gold" style="width: 38px; height: 38px; padding: 0; border-radius: 50%;" onclick="playTrack('${safeEnc}', '${safeUri}')"><i class="fas fa-play"></i></button>
        </div>
        `;
    }).join('') || '<p style="text-align:center; padding:40px; color:var(--text-muted);">Empty Playlist</p>';
    modal.style.display = 'flex';
}

async function playPlaylist(idx) {
    if (!selectedGuildId) return;
    try {
        const resp = await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({ user_id: currentUserId, guild_id: selectedGuildId, action: 'play_playlist', playlist_index: idx })
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            showNotification("Loading", "กำลังโหลด", "Playlist added to queue.", "เพิ่มเพลย์ลิสต์ลงคิวแล้ว", "success");
            switchTab('player', document.querySelector('.sidebar-btn'));
        }
    } catch (e) { console.error(e); }
}

async function deletePlaylist(idx) {
    if (!confirm("Delete this playlist?")) return;
    try {
        await smartFetch('/api/playlist', { method: 'POST', body: JSON.stringify({ user_id: currentUserId, action: 'delete', index: idx }) });
        renderCollection();
    } catch (e) { console.error(e); }
}

async function removeFavorite(uri) {
    if (!currentUserId) return;
    try {
        // Optimistic Remove
        if (window.userFavorites) {
            window.userFavorites = window.userFavorites.filter(f => f.uri !== uri);
            updateFavoriteButton();
        }

        await smartFetch('/api/playlist', { method: 'POST', body: JSON.stringify({ user_id: currentUserId, action: 'remove_favorite', uri }) });

        // Secondary control to ensure bot state is updated if it was the currently playing song
        if (window.currentTrack && window.currentTrack.uri === uri) {
            await sendControl('favorite', window.currentTrack);
        }

        renderCollection();
    } catch (e) { console.error(e); }
}

// Integration to update stats in sidebar
async function updateDashStats() {
    if (document.hidden) return;
    try {
        if (window.fetchGlobalStats) {
            await window.fetchGlobalStats();
            const s = document.getElementById('stat-servers');
            const u = document.getElementById('stat-users');
            if (s) document.getElementById('dash-server-count').textContent = s.textContent;
            if (u) document.getElementById('dash-user-count').textContent = u.textContent;
        }
    } catch (e) { }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
    setInterval(updateDashStats, 60000);
    setTimeout(renderCollection, 1000);
});

// CSS Injection
const styleSheet = document.createElement('style');
styleSheet.innerHTML = `
.folder-card { transition: 0.3s; }
.folder-card:active { transform: scale(0.98); }
.qi-thumb { transition: 0.3s; }
.queue-item:hover { background: rgba(255,255,255,0.08) !important; }
`;
document.head.appendChild(styleSheet);




// AUTO-INIT: If profile is already loaded in script.js, trigger dashboard logic immediately
if (window.userProfile) {
    // Ensure DOM is ready before trying to update UI elements
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            if (typeof onUserLoggedIn === 'function') onUserLoggedIn(window.userProfile);
        });
    } else {
        if (typeof onUserLoggedIn === 'function') onUserLoggedIn(window.userProfile);
    }
}
