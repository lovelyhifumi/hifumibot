"""Discord 접속 없이 알림 형식과 기록 복구를 검증합니다."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from bot import NotificationBot, youtube_ids
from subscriptions import marker


class NotificationFormatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages = []
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.guild = SimpleNamespace(id=1, me=object())
        self.channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True, embed_links=True)
        self.channel.send = AsyncMock(side_effect=self.send)
        self.channel.history.side_effect = self.history
        self.row = dict(guild_id=1, channel_id=10, kind='youtube', source='A',
                        anchor_id=100, baseline='[]')

    async def history(self, **kwargs):
        for message in self.messages:
            if message.id > kwargs['after'].id:
                yield message

    async def send(self, **kwargs):
        self.messages.append(self.message(kwargs['content'], id=200 + len(self.messages)))

    def message(self, content='', author=123, embeds=(), id=101):
        return SimpleNamespace(id=id, content=content, author=SimpleNamespace(id=author), embeds=embeds)

    async def deliver(self, ids, row=None):
        # 매번 새 인스턴스를 생성해 재시작 후 캐시 없는 복구도 검증합니다.
        client = NotificationBot()
        client._connection.user = SimpleNamespace(id=123)
        with patch.object(client, 'get_channel', return_value=self.channel):
            await client.deliver(row or self.row, [dict(id=value, title='title', url='unused') for value in ids])

    async def test_plain_message_and_restart(self):
        await self.deliver(['9tybLjvOGs4'])
        self.channel.send.assert_awaited_once_with(
            content='🔔 새 영상 업로드!\nhttps://www.youtube.com/watch?v=9tybLjvOGs4')
        await self.deliver(['9tybLjvOGs4'])
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_legacy_sources_and_other_authors(self):
        legacy = discord.Embed()
        legacy.set_footer(text=marker('youtube', 'A', 'aaaaaaaaaaa'))
        wrong_source = discord.Embed()
        wrong_source.set_footer(text=marker('youtube', 'B', 'bbbbbbbbbbb'))
        self.messages = [self.message(embeds=[legacy]), self.message(embeds=[wrong_source]),
                         self.message('https://www.youtube.com/watch?v=bbbbbbbbbbb', author=456)]
        await self.deliver(['aaaaaaaaaaa', 'bbbbbbbbbbb'])
        self.channel.send.assert_awaited_once_with(
            content='🔔 새 영상 업로드!\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb')

    async def test_multiple_subscriptions_with_conversation(self):
        self.messages = [self.message('https://www.youtube.com/watch?v=aaaaaaaaaaa'),
                         self.message('conversation', author=456, id=102)]
        await self.deliver(['aaaaaaaaaaa'])
        await self.deliver(['bbbbbbbbbbb'], dict(self.row, source='B'))
        await self.deliver(['bbbbbbbbbbb'], dict(self.row, source='B'))
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_incomplete_history_sends_nothing(self):
        async def broken_history(**kwargs):
            yield self.message('https://www.youtube.com/watch?v=aaaaaaaaaaa')
            raise RuntimeError('history unavailable')
        self.channel.history.side_effect = broken_history
        with self.assertRaises(RuntimeError):
            await self.deliver(['aaaaaaaaaaa', 'bbbbbbbbbbb'])
        self.channel.send.assert_not_awaited()

    def test_url_extraction(self):
        self.assertEqual(youtube_ids('https://youtu.be/9tybLjvOGs4?si=test'), {'9tybLjvOGs4'})
        self.assertEqual(youtube_ids('https://www.youtube.com/watch?feature=share&v=9tybLjvOGs4'),
                         {'9tybLjvOGs4'})
        self.assertEqual(youtube_ids('https://youtube.com.evil/watch?v=9tybLjvOGs4'), set())


if __name__ == '__main__':
    unittest.main()
