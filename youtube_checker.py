import os
import feedparser
from config import YOUTUBE_CHANNEL_ID
from pathlib import Path

BASE_DIR = Path(__file__).parent
LAST_VIDEO_FILE = BASE_DIR / "data" / "last_video.txt"

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
    if not os.path.exists(LAST_VIDEO_FILE):
        return None

    with open(LAST_VIDEO_FILE, "r") as f:
        return f.read().strip()


def save_last_video(video_id):
    with open(LAST_VIDEO_FILE, "w") as f:
        f.write(video_id)