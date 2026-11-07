"""
Video Downloader Service per video social (YouTube, Shorts, TikTok, Instagram Reels, X/Twitter)
e video diretti tramite yt-dlp.
"""

import os
import re
import glob
from typing import Optional
import yt_dlp

# Regex per identificare link a video su YouTube, Shorts, TikTok, Instagram Reels, X (Twitter) o file video
URL_PATTERN = re.compile(
    r'https?://[^\s<>"]*?'
    r'(?:'
    r'youtube\.com/(?:watch\?v=|shorts/|live/|embed/)[a-zA-Z0-9_-]+|'
    r'youtu\.be/[a-zA-Z0-9_-]+|'
    r'(?:vm|vt)\.tiktok\.com/[a-zA-Z0-9_-]+|'
    r'tiktok\.com/@[a-zA-Z0-9_.-]+/video/\d+|'
    r'instagram\.com/(?:reel|reels|p)/[a-zA-Z0-9_-]+|'
    r'(?:twitter|x)\.com/[a-zA-Z0-9_]+/status/\d+|'
    r'[a-zA-Z0-9_./-]+\.(?:mp4|mov|webm)'
    r')[^\s<>"]*',
    re.IGNORECASE
)

class VideoDownloaderService:
    """Scarica e gestisce video social per l'elaborazione multimodale."""
    
    DOWNLOAD_DIR = "/tmp/market_sentinel_videos"

    @classmethod
    def extract_video_url(cls, text: str) -> Optional[str]:
        """Trova e restituisce il primo URL video presente nel testo del messaggio."""
        if not text:
            return None
        match = URL_PATTERN.search(text)
        if match:
            clean_url = match.group(0).rstrip(".,!?;:)'\"]}")
            return clean_url
        return None

    @classmethod
    def download_video(cls, url: str, max_filesize_mb: int = 40) -> Optional[str]:
        """
        Scarica il video in un file locale temporaneo utilizzando yt-dlp.
        Restituisce il path assoluto del file video scaricato o None in caso di errore.
        """
        os.makedirs(cls.DOWNLOAD_DIR, exist_ok=True)
        out_template = os.path.join(cls.DOWNLOAD_DIR, "%(id)s.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': max_filesize_mb * 1024 * 1024,
            'socket_timeout': 20,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None
                
                # Determina il percorso del file
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename):
                    return filename
                
                # Fallback nel caso l'estensione differisca (es. webm -> mp4 o viceversa)
                video_id = info.get("id")
                if video_id:
                    matches = glob.glob(os.path.join(cls.DOWNLOAD_DIR, f"{video_id}.*"))
                    for m in matches:
                        if os.path.exists(m) and os.path.getsize(m) > 0:
                            return m
            return None
        except Exception as e:
            print(f"[VideoDownloaderService] Errore durante il download da {url}: {e}")
            return None

    @classmethod
    def cleanup(cls, file_path: Optional[str]):
        """Rimuove in sicurezza il file temporaneo."""
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"[VideoDownloaderService] Errore eliminazione {file_path}: {e}")
