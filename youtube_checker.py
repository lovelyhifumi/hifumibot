import os
import feedparser
from config import YOUTUBE_CHANNEL_ID
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LAST_VIDEO_FILE = DATA_DIR / "last_video.txt"

RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"


def get_latest_video():
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        return None

    entry = feed.entries[0]

    return {
        "id": entry.yt_videoid,
        "link": entry.link
    }


def load_last_video():
    if not LAST_VIDEO_FILE.exists():
        return None

    with open(LAST_VIDEO_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_last_video(video_id):
    # data 폴더가 없으면 자동 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(LAST_VIDEO_FILE, "w", encoding="utf-8") as f:
        f.write(video_id)