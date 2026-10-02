"""구독 설정만 SQLite에 저장합니다. 마지막 발송 ID는 저장하지 않습니다."""
import json
import sqlite3


class SubscriptionStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            kind TEXT NOT NULL, source TEXT NOT NULL,
            anchor_id INTEGER NOT NULL, baseline TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id, kind, source))''')
        self.db.commit()

    def put(self, guild_id, channel_id, kind, source, anchor_id, items):
        with self.db:
            self.db.execute('INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?)'
                            ' ON CONFLICT DO NOTHING',
                            (guild_id, channel_id, kind, source, anchor_id,
                             json.dumps([item['id'] for item in items])))

    def all(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM subscriptions')]

    def channel(self, guild_id, channel_id):
        return [row for row in self.all() if row['guild_id'] == guild_id
                and row['channel_id'] == channel_id]

    def remove(self, guild_id, channel_id, kind, source):
        with self.db:
            result = self.db.execute('DELETE FROM subscriptions WHERE '
                                    'guild_id=? AND channel_id=? AND kind=? AND source=?',
                                    (guild_id, channel_id, kind, source))
        return bool(result.rowcount)

    def remove_guild(self, guild_id):
        with self.db:
            self.db.execute('DELETE FROM subscriptions WHERE guild_id=?', (guild_id,))

    def close(self):
        self.db.close()


def marker(kind, source, item_id):
    return f'notify:v1:{kind}:{source}:{item_id}'


def pending_items(items, baseline, seen):
    # 목록 순서가 바뀌거나 이전 항목이 재등장해도 다시 발송하지 않습니다.
    known = set(baseline) | set(seen)
    pending = []
    for item in items:
        if item['id'] not in known:
            pending.append(item)
            known.add(item['id'])
    return pending
