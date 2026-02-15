/* 
   Dashboard Logic - Cyori (Unified & Fixed)
*/

// ==========================================
// CONFIGURATION
// ==========================================
// --- ZERO-DELAY INTERNAL RUNNER ---
// ยิงเข้าหาตัวเอง (Pages Function) เพื่อประหยัดเวลาและไม่มี Delay
const IS_LOCAL_DASH = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
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

function control(action, value = null) {
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

    let percent = 0;
    if (totalMs > 0) {
        percent = Math.min((currentMs / totalMs) * 100, 100);
    }

    if (progressBar) progressBar.style.width = `${percent}%`;
    if (timeCurrent) timeCurrent.textContent = formatTime(currentMs);
    if (timeTotal) timeTotal.textContent = formatTime(totalMs);
}

function formatTime(ms) {
    if (ms === Infinity || ms >= 36000000) return "LIVE";
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

function onUserLoggedIn(user) {
    showDashboard();
    if (user) {
        const nameEl = document.getElementById('user-name');
        const avatarEl = document.getElementById('user-avatar');
        const discEl = document.getElementById('user-discriminator');

        if (nameEl) nameEl.textContent = user.username;
        if (discEl) discEl.textContent = `#${user.discriminator || '0000'}`;
        if (avatarEl) {
            const avatarUrl = user.avatar
                ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
                : `https://cdn.discordapp.com/embed/avatars/${parseInt(user.id) % 5}.png`;
            avatarEl.src = avatarUrl;
        }
        currentUserId = user.id;
        startAutoConnect(user.id);

        // Init Favorites
        setTimeout(renderFavorites, 500); // Small delay to ensure data populated
    }
}

// ... (Existing functions) ...

// ==========================================
// 7. FAVORITES / COLLECTION
// ==========================================

function renderFavorites() {
    const list = document.getElementById('favorites-list');
    if (!list) return;

    let favs = [];
    // Data populated by script.js into window.userPremium from /api/user_info
    if (window.userPremium && window.userPremium.favorites) {
        favs = window.userPremium.favorites;
    }

    if (!favs || favs.length === 0) {
        list.innerHTML = `
            <div class="queue-empty" style="text-align: center; padding: 40px; color: var(--text-muted);">
                <i class="fas fa-heart" style="font-size: 3rem; margin-bottom: 15px; opacity: 0.3; color: #ff5555;"></i>
                <p>No favorites found.</p>
                <p style="font-size: 0.9em; opacity: 0.7;">Click the [❤️] button on the player to save songs!</p>
            </div>`;
        return;
    }

    list.innerHTML = favs.map((track) => {
        const safeTitle = (track.title || "Unknown").replace(/'/g, "\\'");
        const safeUri = (track.uri || "").replace(/'/g, "\\'");
        // Encoded might be missing in older saves, nice to have but uri is backup
        const encoded = track.encoded || "";

        return `
        <div class="queue-item" onclick="playFavorite('${encoded}', '${safeUri}')" style="cursor: pointer;">
            <div class="result-icon" style="color:#ff5555; width:30px;"><i class="fas fa-heart"></i></div>
            <div class="queue-details">
                <span class="queue-title">${track.title}</span>
                <span class="queue-artist">${track.author || '-'}</span>
            </div>
            <div class="queue-action">
                <i class="fas fa-play-circle" style="color: var(--gold-primary); font-size: 1.2rem;"></i>
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

    await sendControl('play', payload);
}

function showDashboard() {
    const loginWall = document.getElementById('login-wall');
    const dashboardContainer = document.getElementById('dashboard-container');
    if (loginWall) loginWall.style.display = 'none';
    if (dashboardContainer) dashboardContainer.style.display = 'block';
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

    // Start Realtime Engine
    initRealtime(guildId);
}

// =========================================
// REALTIME ENGINE (ZERO DELAY)
// =========================================
function initRealtime(guildId) {
    if (wsConnection) {
        try { wsConnection.close(); } catch (e) { }
    }

    // Determine WS URL (Smart Direct Logic)
    let wsUrl = '';

    // 1. LOCAL ENVIRONMENT OPTIMIZATION (Zero Proxy Latency)
    // If web is running locally, connect DIRECTLY to bot on localhost:8000
    if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
        // Default aiohttp port is often 8000 or 8080. Using 8000 as standard.
        // If bot uses different port, user can update here easily.
        wsUrl = `ws://${location.hostname}:8000/api/gateway`;
        console.log("[Realtime] Local Environment -> Direct Connect:", wsUrl);
    }
    // 2. REMOTE / PRODUCTION
    else if (BOT_API.startsWith('http')) {
        wsUrl = BOT_API.replace('http', 'ws');
        // Handle standard proxy path replacement
        if (wsUrl.endsWith('proxy')) wsUrl = wsUrl.replace('proxy', 'gateway');
        else if (!wsUrl.includes('gateway')) wsUrl += '/gateway'; // Guess endpoint
    }
    // 3. RELATIVE / REVERSE PROXY
    else {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        wsUrl = `${proto}//${location.host}/api/gateway`;
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
                        duration: d.len,
                        title: d.title || 'Nothing Playing',
                        author: d.author || '-',
                        thumbnail: d.thumb,
                        volume: d.vol || 100,
                        queue: [] // WS doesn't send full queue yet
                    });
                }
            } catch (x) { }
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
        const data = await res.json();
        if (!data.error) updatePlayerUI(data);
    } catch (e) {
        console.error("Fetch Status Error:", e);
    }
}

let isRequesting = false; // Guard for overlapping requests

async function sendControl(action, value = null) {
    if (!selectedGuildId || isRequesting) return;

    // REALTIME SOCKET SEND (Fastest)
    if (isRealtime && wsConnection && wsConnection.readyState === WebSocket.OPEN) {
        wsConnection.send(JSON.stringify({
            op: 'control',
            guild_id: selectedGuildId,
            action: action,
            value: value
        }));
        // Optimistic UI handled by wrapper
        return;
    }

    if (isRealtime) return; // If realtime connected but busy, wait.

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
        // Use branding thumbnail if provided by API, else logo
        if (img) img.src = data.thumbnail || "logo-circle.png";
        if (playIcon) playIcon.className = 'fas fa-play';
        updateProgressUI(0, 0); // Reset to 0:00 / 0:00
        playerState.paused = true;
        playerState.position = 0;
        playerState.duration = 0;
        if (btnShuffle) btnShuffle.classList.remove('active');
        if (btnLoop) btnLoop.classList.remove('active');
        renderQueue([]); // Clear queue list
        return;
    }

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
        if (loopMode !== "off") {
            btnLoop.classList.add('active');
            btnLoop.querySelector('i').className = (loopMode === 'track' || loopMode === 'song') ? 'fas fa-redo-alt' : 'fas fa-redo';
        } else {
            btnLoop.classList.remove('active');
            btnLoop.querySelector('i').className = 'fas fa-redo';
        }
    }

    // Update Progress Data
    playerState.position = data.position || 0;
    playerState.duration = data.duration || 1;
    playerState.paused = data.paused;
    playerState.lastUpdate = Date.now();

    updateProgressUI(playerState.position, playerState.duration);

    if (data.queue) renderQueue(data.queue);
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

        const safeUri = uri.replace(/'/g, "\\'");
        return `
            <div class="search-result-item" onclick="playTrack('${track.encoded}', '${safeUri}')">
                <div class="result-icon">${icon}</div>
                <div class="result-info">
                    <span class="result-title">${track.title}</span>
                    <span class="result-author">${track.author} • ${formatTime(track.length)}</span>
                </div>
                <div class="result-action">
                    <i class="fas fa-play-circle"></i>
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

    const payload = JSON.stringify({
        encoded: encoded,
        uri: uri,
        source: 'dashboard'
    });

    await sendControl('play', payload);
}


// ==========================================
// 6. INITIALIZATION & EVENTS
// ==========================================

function attachSeekListener() {
    const bar = document.getElementById('progress-bar');
    if (bar && !bar.hasAttribute('data-listening')) {
        bar.addEventListener('click', seekTrack);
        bar.setAttribute('data-listening', 'true');
        // console.log("[Dashboard] Seek listener attached.");
    }
}

// Ensure listener is attached after UI updates
const originalUpdatePlayerUI = updatePlayerUI;
updatePlayerUI = function (data) {
    originalUpdatePlayerUI(data);
    attachSeekListener();
};

function renderQueue(queue) {
    const list = document.getElementById('queue-list');
    if (!list) return;

    if (!queue || queue.length === 0) {
        list.innerHTML = '<div class="queue-empty">Queue is empty</div>';
        return;
    }

    list.innerHTML = queue.map((track, index) => `
        <div class="queue-item" id="q-item-${index}" onclick="handleQueueAction('skipto', ${index})" title="Play Now / เล่นทันที">
            <div class="result-icon" style="width:30px; height:30px; font-size:0.8rem; margin-right:10px;">${index + 1}</div>
            <div class="queue-details">
                <span class="queue-title">
                    ${track.title || 'Unknown'} 
                    <span class="play-now-badge" style="font-size:0.7em; opacity:0; margin-left:6px; transition:opacity 0.2s;"><i class="fas fa-forward"></i> Play Now</span>
                </span>
                <span class="queue-artist">${track.author || '-'}</span>
            </div>
            <div class="queue-action" onclick="event.stopPropagation(); handleQueueAction('remove', ${index});" title="Remove / ลบเพลง" style="cursor:pointer; padding:8px; color:#ff4d4d;">
                <i class="fas fa-trash"></i>
            </div>
        </div>
    `).join('');
}

function handleQueueAction(action, index) {
    const item = document.getElementById(`q-item-${index}`);
    if (item) {
        item.style.opacity = '0.5';
        item.style.pointerEvents = 'none';
        if (action === 'remove') item.style.transform = 'scale(0.95)';
    }

    // Call API with slight delay to show visual feedback
    requestAnimationFrame(() => sendControl(action, index));
}

// CSS Injection for hover effect
const style = document.createElement('style');
style.innerHTML = `
.queue-item:hover .play-now-badge { opacity: 0.6 !important; }
.queue-item:active { transform: scale(0.98); }
`;
document.head.appendChild(style);

// ==========================================
// END OF FILE
// ==========================================

