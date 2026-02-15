/* 
   Dashboard Logic - Cyori (Unified & Fixed)
*/

// ==========================================
// CONFIGURATION
// ==========================================
// --- ZERO-DELAY INTERNAL RUNNER ---
// ยิงเข้าหาตัวเอง (Pages Function) เพื่อประหยัดเวลาและไม่มี Delay
const BOT_API = "/api/proxy";

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
let currentLang = 'EN'; // Track current language
let playerState = {
    position: 0,
    duration: 1,
    paused: true,
    lastUpdate: Date.now()
};

// ==========================================
// 1. CORE WRAPPERS (Matching HTML onclicks)
// ==========================================

function control(action, value = null) {
    console.log(`[Dashboard] Action: ${action}`, value);

    if (action === 'stop') {
        // OPTIMIZATION: Immediate UI Reset for Stop button
        updatePlayerUI({ is_playing: false });
        sendControl('stop');
        return;
    }

    // Map actions to BOT API expected terms
    if (action === 'playpause') {
        sendControl('pause');
    } else if (action === 'prev' || action === 'next') {
        sendControl('skip');
    } else if (action === 'volume') {
        handleVolume(value);
    } else {
        sendControl(action, value);
    }
}

/**
 * Seek track by clicking progress bar
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

    console.log(`[Dashboard] Seeking to: ${seekPos}ms (${Math.round(percent * 100)}%)`);

    // Update local UI immediately for responsiveness
    updateProgressUI(seekPos, playerState.duration);

    // Send to bot
    sendControl('seek', seekPos);
}

// ==========================================
// 2. INTERNAL LOGIC
// ==========================================

// Start local timer for smooth updates
function startLocalTimer() {
    updateLocalTimer();
    requestAnimationFrame(startLocalTimer);
}
requestAnimationFrame(startLocalTimer);

function updateLocalTimer() {
    if (!playerState.paused && playerState.duration > 0) {
        const now = Date.now();
        const elapsed = now - playerState.lastUpdate;
        let estimatedPos = playerState.position + elapsed;

        if (estimatedPos > playerState.duration) estimatedPos = playerState.duration;
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
    if (ms === Infinity || ms >= 36000000) return "LIVE"; // Handle streams/infinite tracks
    if (!ms || isNaN(ms) || ms < 0) return "0:00";

    const seconds = Math.floor(ms / 1000);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

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
    }
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
    if (statusInterval) clearInterval(statusInterval);
    statusInterval = setInterval(fetchStatus, 5000); // Optimized: 5s interval to save Worker requests
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

function renderQueue(queue) {
    const list = document.getElementById('queue-list');
    if (!list) return;

    if (!queue || queue.length === 0) {
        list.innerHTML = '<div class="queue-empty">Queue is empty</div>';
        return;
    }

    list.innerHTML = queue.map((track, index) => `
        <div class="queue-item">
            <div class="result-icon" style="width:30px; height:30px; font-size:0.8rem; margin-right:10px;">${index + 1}</div>
            <div class="queue-details">
                <span class="queue-title">${track.title || 'Unknown'}</span>
                <span class="queue-artist">${track.author || '-'}</span>
            </div>
        </div>
    `).join('');
}
