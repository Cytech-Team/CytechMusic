# 🎵 CytechMusic Bot (Legacy)

**Advanced Discord Music Bot (Open Source)** built with `discord.py` and `Lavalink`. 
This is the **Legacy Version** of the bot, now open-sourced for the community to use, learn, and host.

> [!NOTE]
> **Project Status**: This repository is **ARCHIVED** and no longer actively maintained. 
> For the latest, high-performance version, please check out our new project: **[Cyori (Private)](https://github.com/CytechNaRak/Cyori)**. Cyori is built on a completely new architecture with 70%+ improvement in speed and stability.

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
- **FFmpeg**

### 1. Clone the Repository
```bash
git clone https://github.com/CytechNaRak/CytechMusic.git
cd CytechMusic
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configuration (.env)
1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your details (Bot Token, MongoDB URI, Lavalink, etc.).

> [!IMPORTANT]
> **SECURITY NOTE**: Never commit your `.env` file to a public repository. It contains sensitive tokens that can be used to control your bot or access your database.

### 4. Run the Bot
```bash
python main.py
```

---

## 🛠️ Tech Stack
- **Library**: `discord.py`
- **Database**: `MongoDB` (Motor for async)
- **Audio Node**: `Lavalink` (v3 or v4)
- **Payment**: `Stripe` (Optional)
- **Platform**: Python 3.10+

---

## 📝 Commands List

| Command | Description |
| :--- | :--- |
| **/play [query]** | Play a song or playlist from URL or search. |
| **/stop** | Stop playback and clear the queue. |
| **/skip** | Skip the current song. |
| **/pause** | Pause/Resume playback. |
| **/volume [1-200]** | Adjust volume (Premium needed for >100). |
| **/queue** | Show the current music queue. |
| **/loop** | Toggle loop (Track/Queue/Off). |
| **/seek [time]** | Seek to a timestamp (e.g., `1:30`). |
| **/nowplaying** | Show current song info and controller. |

---

## 👥 Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License
Distributed under the [MIT License](LICENSE). See `LICENSE` for more information.

---
**CytechMusic** is a free project for the community. Developed with ❤️ by **Cytech Team**.
