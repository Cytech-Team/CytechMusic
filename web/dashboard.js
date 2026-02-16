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

        // Init Favorites & Recommendations
        setTimeout(() => {
            renderCollection();
            fetchRecommendations();
        }, 500);
    }
}

function switchTab(tabId, btn) {
    const tabs = document.querySelectorAll('.dash-tab-content');
    tabs.forEach(t => {
        t.style.opacity = '0';
        setTimeout(() => {
            t.style.display = 'none';
        }, 200);
    });

    const target = document.getElementById(`tab-${tabId}`);
    if (target) {
        setTimeout(() => {
            target.style.display = 'block';
            setTimeout(() => target.style.opacity = '1', 50);
        }, 210);
    }

    const btns = document.querySelectorAll('.sidebar-btn');
    btns.forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    if (tabId === 'favorites') renderCollection();
}

// ==========================================
// 7. COLLECTION / PLAYLISTS (Enhanced)
// ==========================================

function renderCollection() {
    renderFavorites();
    renderCustomPlaylists();
    updatePlaylistLimits();
}

function renderFavorites() {
    const list = document.getElementById('favorites-list');
    if (!list) return;

    let favs = [];
    if (window.userPremium && window.userPremium.favorites) {
        favs = window.userPremium.favorites;
    }

    if (!favs || favs.length === 0) {
        list.innerHTML = `
            <div class="queue-empty" style="text-align: center; padding: 20px; color: var(--text-muted); background: rgba(0,0,0,0.1); border-radius: 12px;">
                <p>No favorites yet.</p>
            </div>`;
        return;
    }

    list.innerHTML = favs.map((track) => {
        const safeTitle = (track.title || "Unknown").replace(/'/g, "\\'");
        const safeUri = (track.uri || "").replace(/'/g, "\\'");
        const encoded = track.encoded || "";

        return `
        <div class="queue-item" onclick="playFavorite('${encoded}', '${safeUri}')" style="cursor: pointer; padding: 8px 12px; margin-bottom: 5px;">
            <div class="result-icon" style="color:#ff5555; width:24px; font-size: 0.8rem;"><i class="fas fa-heart"></i></div>
            <div class="queue-details">
                <span class="queue-title" style="font-size: 0.9rem;">${track.title}</span>
                <span class="queue-artist" style="font-size: 0.8rem;">${track.author || '-'}</span>
            </div>
            <div class="queue-action">
                <i class="fas fa-play-circle" style="color: var(--gold-primary);"></i>
            </div>
        </div>
        `;
    }).join('');
}

function renderCustomPlaylists() {
    const container = document.getElementById('custom-playlists-list');
    if (!container) return;

    const playlists = (window.userPremium && window.userPremium.playlists) ? window.userPremium.playlists : [];

    if (playlists.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1/-1; text-align: center; padding: 30px; background: rgba(255,255,255,0.02); border-radius: 15px; border: 1px dashed rgba(255,255,255,0.1);">
                <i class="fas fa-folder-plus" style="font-size: 2rem; opacity: 0.2; margin-bottom: 10px;"></i>
                <p style="color: var(--text-muted);">No playlists created.</p>
            </div>`;
        return;
    }

    container.innerHTML = playlists.map((pl, idx) => `
        <div class="playlist-card glass-effect" style="padding: 15px; border-radius: 16px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); transition: 0.3s; position: relative;">
            <div style="font-size: 1.5rem; margin-bottom: 10px; color: var(--gold-primary);"><i class="fas fa-music"></i></div>
            <h5 style="margin: 0; font-size: 1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pl.name}</h5>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin: 5px 0 10px 0;">${pl.tracks ? pl.tracks.length : 0} Tracks</p>
            
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-primary" style="flex: 1; padding: 5px; font-size: 0.75rem;" onclick="playPlaylist(${idx})">Play</button>
                <button class="btn-glass" style="width: 30px; height: 30px; padding: 0; color: #ff4444;" onclick="deletePlaylist(${idx})"><i class="fas fa-trash"></i></button>
            </div>
        </div>
    `).join('');
}

function updatePlaylistLimits() {
    const info = document.getElementById('playlist-limit-info');
    if (!info || !window.userPremium || !window.userPremium.limits) return;

    const { used, total } = window.userPremium.limits;
    info.textContent = `Playlists: ${used}/${total}`;
    if (used >= total) info.style.color = '#ffaa00';
}

// --- Playlist Management Logic ---

function createNewPlaylistPrompt() {
    document.getElementById('playlist-modal').style.display = 'flex';
    document.getElementById('new-playlist-name').focus();
}

async function confirmCreatePlaylist() {
    const nameInput = document.getElementById('new-playlist-name');
    const name = nameInput.value.trim();
    if (!name) return;

    document.getElementById('playlist-modal').style.display = 'none';
    nameInput.value = '';

    try {
        const res = await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({
                user_id: currentUserId,
                action: 'create',
                name: name
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showNotification("Success", "สำเร็จ", "Playlist created successfully.", "สร้างเพลย์ลิสต์เรียบร้อยแล้ว", "success");
            // Re-fetch user data to get updated list
            if (typeof window.fetchPremiumStatus === 'function') await window.fetchPremiumStatus();
            renderCollection();
        } else {
            showNotification("Error", "ข้อผิดพลาด", data.error, data.error);
        }
    } catch (e) {
        console.error("Create Playlist Error:", e);
    }
}

async function deletePlaylist(index) {
    if (!confirm("Are you sure you want to delete this playlist?")) return;

    try {
        await smartFetch('/api/playlist', {
            method: 'POST',
            body: JSON.stringify({
                user_id: currentUserId,
                action: 'delete',
                index: index
            })
        });
        if (typeof window.fetchPremiumStatus === 'function') await window.fetchPremiumStatus();
        renderCollection();
    } catch (e) { console.error(e); }
}

async function playPlaylist(index) {
    if (!selectedGuildId) {
        alert("Please join a voice channel first!");
        return;
    }
    const pl = window.userPremium.playlists[index];
    if (!pl || !pl.tracks || pl.tracks.length === 0) return;

    showNotification("Playlist Playing", "กำลังเล่นเพลย์ลิสต์", `Added ${pl.tracks.length} tracks to queue.`, `เพิ่ม ${pl.tracks.length} เพลงลงคิวแล้ว`, "success");

    // Start playing first track, then add others
    for (let i = 0; i < pl.tracks.length; i++) {
        const t = pl.tracks[i];
        await sendControl('play', JSON.stringify({
            encoded: t.encoded,
            uri: t.uri,
            source: 'playlist'
        }));
        // Small delay between batch play to avoid spam
        await new Promise(r => setTimeout(r, 200));
    }
}

// ==========================================
// 8. RECOMMENDED CLIPS
// ==========================================

async function fetchRecommendations() {
    const list = document.getElementById('recommended-list');
    if (!list) return;

    try {
        const res = await smartFetch(`?action=recommended&guild_id=${selectedGuildId || ''}`);
        const data = await res.json();

        if (data.results) {
            renderRecommendations(data.results);
        }
    } catch (e) {
        console.error("Recommended Fetch Error:", e);
    }
}

function renderRecommendations(tracks) {
    const list = document.getElementById('recommended-list');
    if (!list) return;

    list.innerHTML = tracks.map(track => {
        const safeTitle = (track.title || "").replace(/'/g, "\\'");
        const safeUri = (track.uri || "").replace(/'/g, "\\'");

        return `
        <div class="recommended-card" onclick="playTrack('${track.encoded}', '${safeUri}')" 
             style="min-width: 180px; cursor: pointer; transition: 0.3s; position: relative; group">
            <div style="position: relative; overflow: hidden; border-radius: 12px; aspect-ratio: 16/9; background: #000;">
                <img src="${track.thumbnail}" style="width: 100%; height: 100%; object-fit: cover; opacity: 0.8; transition: 0.5s;" 
                     onerror="this.src='logo-circle.png'">
                <div class="play-overlay" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.4); opacity: 0; transition: 0.3s;">
                    <i class="fas fa-play-circle" style="font-size: 2rem; color: #fff;"></i>
                </div>
            </div>
            <div style="margin-top: 10px;">
                <h4 style="font-size: 0.85rem; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${track.title}</h4>
                <p style="font-size: 0.75rem; color: var(--text-muted); margin: 3px 0 0 0;">${track.author}</p>
            </div>
        </div>
        `;
    }).join('');

    // Add hover styles via JS injected CSS if not in style.css
    if (!document.getElementById('rec-styles')) {
        const style = document.createElement('style');
        style.id = 'rec-styles';
        style.innerHTML = `
            .recommended-card:hover { transform: translateY(-5px); }
            .recommended-card:hover .play-overlay { opacity: 1 !important; }
            .recommended-card:hover img { transform: scale(1.1); opacity: 1 !important; }
            .horizontal-scroll::-webkit-scrollbar { height: 4px; }
            .horizontal-scroll::-webkit-scrollbar-thumb { background: rgba(212, 175, 55, 0.3); border-radius: 10px; }
        `;
        document.head.appendChild(style);
    }
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

    // 1. LOCAL ENVIRONMENT (Direct Connect)
    if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
        wsUrl = `ws://${location.hostname}:8000/api/gateway`;
    }
    // 2. REMOTE / PRODUCTION (Using Cloudflare Gateway Proxy)
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
        is_stream: data.is_stream,
        encoded: data.encoded
    };

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
            <div class="search-result-item" style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 12px; background: rgba(255,255,255,0.03); margin-bottom: 8px; transition: 0.2s;">
                <div class="result-icon" onclick="playTrack('${track.encoded}', '${safeUri}')" style="cursor: pointer;">${icon}</div>
                <div class="result-info" onclick="playTrack('${track.encoded}', '${safeUri}')" style="flex: 1; cursor: pointer;">
                    <span class="result-title" style="display: block; font-weight: 500;">${track.title}</span>
                    <span class="result-author" style="font-size: 0.8rem; color: var(--text-muted);">${track.author} • ${formatTime(track.length)}</span>
                </div>
                <div class="result-actions" style="display: flex; gap: 10px;">
                    <button class="btn-glass" onclick="showAddToPlaylistModal('${track.encoded}', '${safeUri}', '${track.title.replace(/'/g, "\\'")}')" 
                            style="width: 32px; height: 32px; border-radius: 50%; padding: 0; font-size: 0.8rem;" title="Add to Playlist">
                        <i class="fas fa-plus"></i>
                    </button>
                    <div onclick="playTrack('${track.encoded}', '${safeUri}')" style="cursor: pointer; color: var(--gold-primary); font-size: 1.2rem;">
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

    await sendControl('play', JSON.stringify({
        encoded: encoded,
        uri: uri,
        source: 'dashboard'
    }));
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

    const playlists = (window.userPremium && window.userPremium.playlists) ? window.userPremium.playlists : [];
    if (playlists.length === 0) {
        container.innerHTML = `<p style="text-align: center; color: #aaa; padding: 20px;">No playlists found. Create one first!</p>`;
        return;
    }

    container.innerHTML = playlists.map((pl, idx) => `
        <button class="btn-glass" onclick="confirmAddTrackToPlaylist(${idx})" 
                style="width: 100%; text-align: left; padding: 12px 15px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <span>${pl.name}</span>
            <i class="fas fa-plus"></i>
        </button>
    `).join('');
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

    list.innerHTML = queue.map((track, index) => {
        const safeTitle = (track.title || "Unknown").replace(/'/g, "\\'");
        const safeUri = (track.uri || "").replace(/'/g, "\\'");
        const encoded = track.encoded || "";

        return `
        <div class="queue-item" id="q-item-${index}" 
             style="display: grid; grid-template-columns: 30px 1fr 80px; align-items: center; gap: 10px; padding: 10px; background: rgba(255,255,255,0.05); margin-bottom: 5px; border-radius: 12px; transition: 0.2s;">
            
            <div class="result-icon" style="text-align: center; color: var(--gold-primary); font-weight: bold; font-size: 0.8rem;">
                ${index + 1}
            </div>
            
            <div class="queue-details" onclick="handleQueueAction('skipto', ${index})" style="overflow: hidden; cursor: pointer;">
                <div class="queue-title" style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-main); font-size: 0.9rem;">
                    ${track.title || 'Unknown'} 
                </div>
                <div class="queue-artist" style="font-size: 0.75rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis;">
                    ${track.author || '-'}
                </div>
            </div>
            
            <div class="queue-actions-row" style="display: flex; gap: 8px; justify-content: flex-end;">
                <button class="btn-glass" onclick="showAddToPlaylistModal('${encoded}', '${safeUri}', '${safeTitle}')" 
                        style="width: 28px; height: 28px; border-radius: 50%; padding: 0; font-size: 0.7rem; color: var(--gold-primary);" title="Add to Playlist">
                    <i class="fas fa-plus"></i>
                </button>
                <div onclick="handleQueueAction('remove', ${index})" 
                     style="width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; color: #ff4d4d; cursor: pointer;">
                    <i class="fas fa-trash"></i>
                </div>
            </div>
        </div>
        `;
    }).join('');
}

async function addToFavorite() {
    if (!window.currentTrack || !playerState.duration) {
        showNotification("No Music", "ไม่มีเพลง", "No music is playing right now.", "ขณะนี้ไม่มีเพลงที่กำลังเล่นอยู่", "error");
        return;
    }

    const icon = document.querySelector('#btn-favorite i');
    if (icon) {
        icon.className = 'fas fa-heart';
        icon.style.color = '#ff5555';
    }

    await sendControl('favorite', window.currentTrack);
    showNotification("Added to Favorites", "เพิ่มแล้ว", "Saved to your collection.", "บันทึกเพลงลงคอลเลคชันแล้ว", "success");
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

