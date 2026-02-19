
import aiohttp
import random
import re
import hmac
import hashlib
import base64
import json
import urllib.parse
from datetime import datetime
from abc import ABC, abstractmethod
from urllib.parse import quote
from math import floor
from typing import Optional, Type, Dict
import bs4
from utils import config

userAgents = [
    'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.1 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/535.11 (KHTML, like Gecko) Chrome/17.0.963.66 Safari/535.11',
    'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/530.4 (KHTML, like Gecko) Chrome/2.0.172.0 Safari/530.4',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_6_8) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.11 Safari/535.19'
]

class LyricsPlatform(ABC):
    @abstractmethod
    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        ...

class A_ZLyrics(LyricsPlatform):
    async def get(self, url) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url=url, headers={'User-Agent': random.choice(userAgents)}) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.text()
        except:
            return ""

    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        link = await self.google_get(title=title, artist=artist)
        if not link:
            return None

        page_content = await self.get(link)
        if not page_content:
            return None
            
        soup = bs4.BeautifulSoup(page_content, "html.parser")
        metadata = [elm.text for elm in soup.find_all('b')]
        
        if not metadata:
            return None
        
        try:
            divs = [i.text for i in soup.find_all('div', {'class': None})]
            lyrics = max(divs, key=len).strip()

            if not lyrics:
                return None

            lyrics_parts = re.split(r"(\[[\w\S_ ]+\:])", lyrics)
            lyrics_parts = [item for item in lyrics_parts if item != ""]

            count = len(lyrics_parts)
            if count > 1:
                if (count % 2) != 0:
                    del lyrics_parts[count-1]
                return {lyrics_parts[i].replace("[", "").replace(":]", ""): self.clear_text(lyrics_parts[i + 1]) for i in range(0, len(lyrics_parts), 2)}
            return {"default": self.clear_text(lyrics_parts[0])}
        except Exception:
            return None

    async def google_get(self, acc=0.6, artist='', title='') -> Optional[str]:
        data = artist + ' ' * (title != '' and artist != '') + title
        encoded_data = quote(data.replace(' ', '+'))
        url = 'https://duckduckgo.com/html/?q=' + encoded_data + '+site%3Aazlyrics.com'
        
        google_page = await self.get(url)
        if not google_page:
            return None

        try:
            results = re.findall(r'(azlyrics\.com\/lyrics\/[a-z0-9]+\/(\w+).html)', google_page)
        except:
            return None
            
        if len(results):
            jaro_artist = 1.0
            jaro_title = 1.0
            
            if artist:
                jaro_artist = self.jaro_distance(artist.replace(' ', '').lower(), results[0][0].lower())
            if title:
                jaro_title = self.jaro_distance(title.replace(' ', '').lower(), results[0][1].lower())
            
            if jaro_artist >= acc and jaro_title >= acc:
                return 'https://www.' + results[0][0]
        return None

    def jaro_distance(self, s1, s2) -> float:
        if s1 == s2:
            return 1.0
    
        len1, len2 = len(s1), len(s2)
        max_dist = floor(max(len1, len2) / 2) - 1
        match = 0
        hash_s1, hash_s2 = [0] * len(s1), [0] * len(s2)
    
        for i in range(len1):
            for j in range(max(0, i - max_dist), min(len2, i + max_dist + 1)):
                if s1[i] == s2[j] and hash_s2[j] == 0:
                    hash_s1[i], hash_s2[j] = 1, 1
                    match += 1
                    break

        if match == 0:
            return 0.0

        t = 0
        point = 0
        for i in range(len1): 
            if hash_s1[i]: 
                while hash_s2[point] == 0: 
                    point += 1
                if s1[i] != s2[point]: 
                    t += 1
                point += 1
        t = t // 2

        return (match / len1 + match / len2 + (match - t) / match) / 3.0

    def clear_text(self, text: str) -> str:
        if text.startswith("\n\n"):
            text = text.replace("\n\n", "", 1)
        return text

class Genius(LyricsPlatform):
    def __init__(self) -> None:
        try:
            import lyricsgenius
            token = getattr(config, "GENIUS_TOKEN", None)
            if token:
                self.genius = lyricsgenius.Genius(token)
            else:
                self.genius = None
        except ImportError:
            self.genius = None

    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        if not self.genius:
            return None
        # genius.search_song is blocking, but lyricsgenius doesn't have a native async version
        # We wrap it in a thread for now or just use it as is if it's acceptable
        # Since this is an async system, we should ideally use run_in_executor
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            song = await loop.run_in_executor(None, lambda: self.genius.search_song(title=title, artist=artist))
            if not song:
                return None
            return {"default": song.lyrics}
        except:
            return None

class Lyrist(LyricsPlatform):
    def __init__(self):
        self.base_url: str = "https://lyrist.vercel.app/api/"

    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        try:
            request_url = self.base_url + urllib.parse.quote(title) + "/" + urllib.parse.quote(artist)
            async with aiohttp.ClientSession() as session:
                async with session.get(url=request_url, headers={'User-Agent': random.choice(userAgents)}) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if "lyrics" in data:
                        return {"default": data["lyrics"]}
        except:
            pass
        return None

class Lrclib(LyricsPlatform):
    def __init__(self):
        self.base_url: str = "https://lrclib.net/api/"

    async def get(self, url, params: dict = None) -> list[dict]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url=url, headers={'User-Agent': random.choice(userAgents)}, params=params) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except:
            return []
        
    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        params = {"q": f"{title} {artist}"}
        result = await self.get(self.base_url + "search", params)
        if result and len(result) > 0:
            return {"default": result[0].get("plainLyrics", "") or result[0].get("lyrics", "")}
        return None

class MusixMatch(LyricsPlatform):
    def __init__(self):
        self.base_url = "https://www.musixmatch.com/ws/1.1/"
        self.headers = {'User-Agent': random.choice(userAgents)}
        self.secret: Optional[str] = None

    async def search_tracks(self, track_query: str, page: int = 1) -> dict:
        url = f"track.search?app_id=web-desktop-app-v1.0&format=json&q={urllib.parse.quote(track_query)}&f_has_lyrics=true&page_size=5&page={page}"
        return await self.make_request(url)

    async def get_track_lyrics(self, track_id: Optional[str] = None, track_isrc: Optional[str] = None) -> dict:
        if not (track_id or track_isrc):
            raise ValueError("Either track_id or track_isrc must be provided.")
        param = f"track_id={track_id}" if track_id else f"track_isrc={track_isrc}"
        url = f"track.lyrics.get?app_id=web-desktop-app-v1.0&format=json&{param}"
        return await self.make_request(url)

    async def get_latest_app(self):
        url = "https://www.musixmatch.com/search"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={**self.headers, "Cookie": "mxm_bab=AB"}) as response:
                html_content = await response.text()
                pattern = r'src="([^"]*/_next/static/chunks/pages/_app-[^"]+\.js)"'
                matches = re.findall(pattern, html_content)
                if not matches:
                    raise Exception("_app URL not found in the HTML content.")
                return matches[-1]

    async def get_secret(self) -> str:
        async with aiohttp.ClientSession() as session:
            js_url = await self.get_latest_app()
            if not js_url.startswith("http"):
                js_url = "https://www.musixmatch.com" + js_url
            async with session.get(js_url, headers=self.headers, timeout=5) as response:
                javascript_code = await response.text()
                pattern = r'from\(\s*"(.*?)"\s*\.split'
                match = re.search(pattern, javascript_code)
                if match:
                    encoded_string = match.group(1)
                    reversed_string = encoded_string[::-1]
                    decoded_bytes = base64.b64decode(reversed_string)
                    return decoded_bytes.decode("utf-8")
                else:
                    raise Exception("Encoded string not found in the JavaScript code.")

    async def generate_signature(self, url: str) -> str:
        current_date = datetime.now()
        date_str = f"{current_date.year}{str(current_date.month).zfill(2)}{str(current_date.day).zfill(2)}"
        message = (url + date_str).encode()

        if not self.secret:
            self.secret = await self.get_secret()

        key = self.secret.encode()
        hash_output = hmac.new(key, message, hashlib.sha256).digest()
        signature = (
            "&signature="
            + urllib.parse.quote(base64.b64encode(hash_output).decode())
            + "&signature_protocol=sha256"
        )
        return signature
    
    async def make_request(self, url: str) -> dict:
        url = url.replace("%20", "+").replace(" ", "+")
        url_full = self.base_url + url
        signed_url = url_full + await self.generate_signature(url_full)

        async with aiohttp.ClientSession() as session:
            async with session.get(signed_url, headers=self.headers, timeout=5) as response:
                if response.status != 200:
                    raise Exception(f"HTTP Error: {response.status} for URL: {signed_url}")
                try:
                    text_data = await response.text()
                    return json.loads(text_data)
                except json.JSONDecodeError:
                    raise Exception(f"Failed to parse JSON. Response: {text_data}")

    async def get_lyrics(self, title: str, artist: str) -> Optional[dict[str, str]]:
        try:
            results = await self.search_tracks(track_query=f"{artist} {title}" if artist else title)
            track_list = results.get("message", {}).get("body", {}).get("track_list")
            if not track_list:
                return None

            track_id = track_list[0]["track"]["track_id"]
            lyric_data = await self.get_track_lyrics(track_id=track_id)
            lyrics_body = lyric_data.get("message", {}).get("body", {}).get("lyrics", {}).get("lyrics_body", "")
            if not lyrics_body:
                return None
            return {"default": lyrics_body}
        except:
            return None

LYRICS_PLATFORMS: Dict[str, Type[LyricsPlatform]] = {
    "lrclib": Lrclib,
    "musixmatch": MusixMatch,
    "azlyrics": A_ZLyrics,
    "lyrist": Lyrist,
    "genius": Genius
}

class LyricsManager:
    def __init__(self):
        self.platforms = {name: cls() for name, cls in LYRICS_PLATFORMS.items()}

    async def get_lyrics(self, title: str, artist: str = "") -> Optional[dict[str, str]]:
        # Function to clean text
        def clean_text(text):
            # Remove content in brackets/parentheses like (feat.) [Official]
            text = re.sub(r"[\(\[].*?[\)\]]", "", text)
            # Remove non-alphanumeric chars usually incorrectly parsed
            # Allow Thai characters (\u0E00-\u0E7F) and common punctuation
            text = re.sub(r"[^\w\s\-\'\u0E00-\u0E7F]", "", text)
            return text.strip()

        clean_title = clean_text(title)
        clean_artist = clean_text(artist)

        search_queries = []
        if clean_artist:
            search_queries.append((clean_title, clean_artist))
        # If artist scraping fails, sometimes title contains everything
        search_queries.append((f"{artist} {title}".strip(), ""))
        
        # Also try raw if cleaning was too aggressive
        if title != clean_title:
            search_queries.append((title, artist))

        print(f"[Lyrics] Searching for: {search_queries[0]}")

        # Priority order: lrclib, musixmatch, lyrist, genius, azlyrics
        # Adjusted priority: lrclib is best for sync, lyrist is fast, others are backups
        platforms_list = ["lrclib", "lyrist", "musixmatch", "genius", "azlyrics"]

        for name in platforms_list:
            platform = self.platforms.get(name)
            if not platform: continue
            
            if name == "genius" and not platform.genius:
                continue

            for t, a in search_queries:
                try:
                    # Don't spam requests too fast if we are retrying
                    lyrics = await platform.get_lyrics(t, a)
                    if lyrics:
                        print(f"[Lyrics] Found on {name}")
                        return lyrics
                except Exception as e:
                    print(f"[Lyrics] Error fetching from {name}: {e}")
                    continue
                    
        return None
