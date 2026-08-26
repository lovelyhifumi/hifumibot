import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("NEXON_API_KEY")

headers = {
    "x-nxopen-api-key": API_KEY
}

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LAST_NOTICE_FILE = DATA_DIR / "last_notice.txt"

url = "https://open.api.nexon.com/maplestory/v1/notice"

def get_notices():
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data['notice']
    except requests.RequestException as e:
        print(f"넥슨 API 오류: {e}")
        return None

def save_last_notice(notice_id):
    DATA_DIR.mkdir(exist_ok=True)
    with open(LAST_NOTICE_FILE, "w") as f:
        f.write(str(notice_id))

def load_last_notice():
    if not LAST_NOTICE_FILE.exists():
        return None
    with open(LAST_NOTICE_FILE, "r") as f:
        return int(f.read().strip())