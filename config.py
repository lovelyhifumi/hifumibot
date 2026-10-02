"""환경변수에는 운영자 인증 정보와 실행 설정만 둡니다."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
TOKEN = os.getenv('TOKEN', '')
CHECK_INTERVAL = max(30, int(os.getenv('CHECK_INTERVAL', '60')))
DATA_DIR = Path(os.getenv('BOT_DATA_DIR', str(BASE_DIR / 'data')))
# 개발 중 지정하면 해당 서버에 즉시 명령어 동기화. 운영 시 비워 둡니다.
TEST_GUILD_ID = os.getenv('TEST_GUILD_ID', '')
