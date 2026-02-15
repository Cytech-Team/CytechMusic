# 🎵 Cyori Bot

**Advanced Discord Music Bot** built with `discord.py` and `Lavalink`. Features high-quality audio, custom filters (Nightcore, 8D, etc.), multi-language support (English/Thai), and robust server settings.

## ✨ Features

### 🎧 Music Playback
- **High Quality Audio**: Powered by Lavalink for lag-free performance.
- **Sources**: Supports YouTube, Spotify, SoundCloud, and more.
- **Controls**: Play, Pause, Skip, Stop, Seek, Volume, Loop (Track/Queue), Shuffle.
- **Queue System**: View queue with pagination, remove songs, swap order.

### 🎚️ Audio Filters
ENHANCE your listening experience with real-time audio effects:
- **Presets**: `Nightcore`, `Vaporwave`, `8D Audio`
- **Manual Adjustments**:
  - `Speed`: Control playback speed.
  - `Karaoke`: Remove vocals for singing along.
  - `Tremolo` & `Vibrato`: Add pitch/volume oscillation effects.
  - `Rotation`: 8D-like rotating audio effect.
  - `Distortion`: Add grit to the sound.
  - `Lowpass`: Muffled/Lo-Fi effect.
  - `ChannelMix`: Custom left/right audio routing.

### ⚙️ Server Settings
Fully configurable per server via the dashboard-like commands:
- **Language**: Switch between **English (EN)** and **Thai (TH)**.
- **DJ System**:
  - **DJ Role**: Assign a specific role for music controls.
  - **DJ Mode**: Restrict strict controls (Skip/Stop/Vol) to DJs/Admins only.
- **Vote System**: Enable voting requirements for specific filters (forces users to vote for the bot).
- **24/7 Mode**: Keep the bot in the voice channel even when inactive.
- **Autoplay**: Automatically play related songs when the queue ends.
- **Setup Channel**: Create a dedicated channel (`#cytech-music`) with a permanent player controller.

### 📊 Info & Utilities
- **Status**: View detailed uptime, CPU/RAM usage, and Lavalink node stats.
- **Ping**: Color-coded latency check.
- **Help**: Dynamic help menu with dropdowns for categories.

---

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.10+
- MongoDB Database
- Lavalink Server (v3 or v4)
- **FFmpeg** (if needed for local handling, though Lavalink handles most)

### 1. Clone the Repository
```bash
git clone https://github.com/YourUsername/Cyori.git
cd Cyori
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```
*Note: Ensure `cytechlink` (local wrapper) is present in the directory.*

### 3. Configuration (.env)
Create a `.env` file in the root directory:
```env
# Bot Credentials
BOT_TOKEN=your_discord_bot_token
APP_ID=your_application_id
OWNER_IDS=123456789,987654321

# Database
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
DB_NAME=Komo

# Lavalink Connection
LAVALINK_HOST=localhost
LAVALINK_PORT=2333
LAVALINK_PASS=youshallnotpass
LAVALINK_ID=MainNode

# API Keys (Optional but recommended)
SPOTIFY_CLIENT_ID=your_spotify_id
SPOTIFY_CLIENT_SECRET=your_spotify_secret
DBL_TOKEN=topgg_api_token
WARNING_SOUND_URL=http://link_to_mp3
```

### 4. Run the Bot
```bash
python main.py
```

---

## 📝 Commands List

| Command | Description |
| :--- | :--- |
| **/play [query]** | Play a song or playlist from URL or search. |
| **/buy [plan]** | Purchase Premium (1mo, 3mo, 6mo, 1yr, Lifetime 789 THB). |
| **/stop** | Stop playback and clear the queue. |
| **/skip** | Skip the current song. |
| **/pause** | Pause/Resume playback. |
| **/volume [1-200]** | Adjust volume (Premium needed for >100). |
| **/queue** | Show the current music queue. |
| **/loop** | Toggle loop (Track/Queue/Off). |
| **/seek [time]** | Seek to a timestamp (e.g., `1:30`). |
| **/join** / **/leave** | Connect/Disconnect from voice. |
| **/nowplaying** | Show current song info and controller. |

### Filter Commands
- `/speed [0.5-2.0]`
- `/nightcore`, `/vaporwave`, `/8d`
- `/karaoke`, `/tremolo`, `/vibrato`, `/rotation`
- `/cleareffect` (Remove all filters)

### Settings Commands (Admin/DJ)
- `/viewsettings` (See current config)
- `/language [en/th]`
- `/setup` (Create music channel)
- `/247` (Toggle 24/7 mode)
- `/autoplay` (Toggle autoplay)
- `/djrole [role]`
- `/djmode` (Toggle Strict Mode)

---

## 👥 Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License
[MIT](https://choosealicense.com/licenses/mit/)
