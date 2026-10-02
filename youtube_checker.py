"""유튜브 채널 주소 해석 및 RSS 조회. 마지막 영상 파일을 사용하지 않습니다."""
import re
from urllib.parse import urlparse, unquote, quote
import requests
import feedparser

CHANNEL_ID = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'DiscordNotificationBot/2.0'


def get_feed(channel_id):
    if not CHANNEL_ID.fullmatch(channel_id):
        raise ValueError('유효한 유튜브 채널 ID가 아닙니다.')
    response = SESSION.get('https://www.youtube.com/feeds/videos.xml',
                           params={'channel_id': channel_id}, timeout=15)
    response.raise_for_status()
    return feedparser.parse(response.content)


def get_channel_name(channel_id):
    name = get_feed(channel_id).feed.get('title', '').strip()
    if not name:
        raise ValueError('채널 이름을 읽지 못했습니다.')
    return name


def get_videos(channel_id):
    feed = get_feed(channel_id)
    videos = []
    for entry in feed.entries:
        video_id = entry.get('yt_videoid')
        if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            continue
        videos.append({'id': video_id, 'title': entry.get('title', '새 영상'),
                       'url': f'https://www.youtube.com/watch?v={video_id}',
                       'date': entry.get('published', '')})
    if not videos:
        raise ValueError('영상 목록을 읽지 못했습니다. 공개 영상이 있는 채널인지 확인해 주세요.')
    return sorted(videos, key=lambda video: (video['date'], video['id']))


def resolve_channel(value):
    value = value.strip()
    if CHANNEL_ID.fullmatch(value):
        return value
    if value.startswith('@'):
        path = '/' + value
    else:
        parsed = urlparse(value if '://' in value else 'https://' + value)
        if parsed.scheme != 'https' or parsed.netloc.lower() not in {
            'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
            raise ValueError('유튜브 채널 주소 또는 @핸들을 입력해 주세요.')
        path = unquote(parsed.path).rstrip('/')
    parts = path.strip('/').split('/')
    if len(parts) >= 2 and parts[0] == 'channel' and CHANNEL_ID.fullmatch(parts[1]):
        return parts[1]
    # 임의 URL을 요청하지 않고 youtube.com의 채널 경로만 허용합니다.
    if parts[0].startswith('@'):
        path = '/' + parts[0]
    elif len(parts) >= 2 and parts[0] in {'c', 'user'}:
        path = '/' + '/'.join(parts[:2])
    else:
        raise ValueError('영상 주소 대신 채널 주소 또는 @핸들을 입력해 주세요.')
    if not parts[0].lstrip('@'):
        raise ValueError('@ 뒤에 채널 핸들을 입력해 주세요.')
    response = SESSION.get('https://www.youtube.com' + quote(path, safe='/@'), timeout=15)
    response.raise_for_status()
    patterns = [r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
                r'<link[^>]+href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"',
                r'<meta[^>]+itemprop="channelId"[^>]+content="(UC[A-Za-z0-9_-]{22})"']
    for pattern in patterns:
        match = re.search(pattern, response.text)
        if match:
            return match.group(1)
    raise ValueError('채널 ID를 찾지 못했습니다. /channel/UC… 주소나 UC로 시작하는 ID로 다시 시도해 주세요.')
