"""네트워크 호출 없이 핵심 중복 방지/구독 격리를 검증합니다."""
import json
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from subscriptions import SubscriptionStore, pending_items


class NotificationTests(unittest.TestCase):
    def test_reordered_and_reappearing_items(self):
        items = [{'id': x} for x in ['old', 'new', 'sent']]
        self.assertEqual(pending_items(items, ['old'], ['sent']), [{'id': 'new'}])
        self.assertEqual(pending_items(items[::-1], ['old'], ['sent', 'new']), [])

    def test_multiple_servers_and_sources_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'subscriptions.sqlite3'
            store = SubscriptionStore(path)
            store.put(1, 10, 'youtube', 'A', 100, [{'id': 'old'}])
            store.put(2, 20, 'youtube', 'A', 200, [{'id': 'different'}])
            store.put(1, 10, 'youtube', 'B', 300, [])
            store.put(1, 10, 'youtube', 'A', 999, [])
            store.close()
            store = SubscriptionStore(path)
            self.assertEqual(len(store.all()), 3)
            self.assertEqual(json.loads(store.channel(1, 10)[0]['baseline']), ['old'])
            self.assertTrue(store.remove(1, 10, 'youtube', 'A'))
            self.assertEqual(len(store.channel(2, 20)), 1)
            store.close()


from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch
import discord
from bot import NotificationBot
from subscriptions import marker


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = NotificationBot()
        self.bot._connection.user = SimpleNamespace(id=123)
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.guild = SimpleNamespace(id=1, me=object())
        self.channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True, embed_links=True)
        self.channel.send = AsyncMock()
        self.row = dict(guild_id=1, channel_id=10, kind='youtube', source='A',
                        anchor_id=100, baseline='["old"]')
        self.items = [dict(id=x, title=x, url='https://www.youtube.com/watch?v='+x)
                      for x in ['old', 'one', 'two']]

    def message(self, source, item, author=123):
        embed = discord.Embed()
        embed.set_footer(text=marker('youtube', source, item))
        return SimpleNamespace(id=101, author=SimpleNamespace(id=author), embeds=[embed])

    async def test_history_ignores_other_sources_and_people(self):
        async def history(**kwargs):
            yield self.message('A', 'one')
            yield self.message('B', 'two')
            yield self.message('A', 'two', author=456)
        self.channel.history.side_effect = history
        with patch.object(self.bot, 'get_channel', return_value=self.channel):
            await self.bot.deliver(self.row, self.items)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs['embed'].footer.text,
                         marker('youtube', 'A', 'two'))

    async def test_history_failure_sends_nothing(self):
        async def history(**kwargs):
            yield self.message('A', 'one')
            raise RuntimeError('history unavailable')
        self.channel.history.side_effect = history
        with patch.object(self.bot, 'get_channel', return_value=self.channel):
            with self.assertRaises(RuntimeError):
                await self.bot.deliver(self.row, self.items)
        self.channel.send.assert_not_awaited()

    async def test_partial_send_is_not_repeated_on_retry(self):
        messages = []
        async def history(**kwargs):
            for message in messages:
                yield message
        self.channel.history.side_effect = history
        async def send(**kwargs):
            if messages:
                raise RuntimeError('temporary send failure')
            messages.append(SimpleNamespace(id=102, author=SimpleNamespace(id=123),
                                            embeds=[kwargs['embed']]))
        self.channel.send.side_effect = send
        with patch.object(self.bot, 'get_channel', return_value=self.channel):
            with self.assertRaises(RuntimeError):
                await self.bot.deliver(self.row, self.items)
            self.channel.send.reset_mock(side_effect=True)
            await self.bot.deliver(self.row, self.items)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs['embed'].footer.text,
                         marker('youtube', 'A', 'two'))


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_preview_and_baseline(self):
        from bot import register
        for kind, source in [('youtube', 'A')]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory, closing(
                    SubscriptionStore(Path(directory) / 'subscriptions.sqlite3')) as store:
                import asyncio
                client = SimpleNamespace(lock=asyncio.Lock(), store=store)
                channel = SimpleNamespace(id=10, send=AsyncMock(return_value=SimpleNamespace(id=100)))
                interaction = SimpleNamespace(guild_id=1, followup=SimpleNamespace(send=AsyncMock()))
                items = [dict(id=x, title=x, url='https://example.com/' + x)
                         for x in ['old', 'latest']]
                with patch('bot.bot', client), patch('bot.setting_channel', return_value=channel):
                    await register(interaction, source, items)
                    embed = channel.send.call_args.kwargs['embed']
                    self.assertEqual(embed.description, 'latest')
                    self.assertEqual(embed.url, 'https://example.com/latest')
                    self.assertFalse(embed.footer.text.startswith('notify:v1:'))
                    row = store.channel(1, 10)[0]
                    self.assertEqual(pending_items(items, json.loads(row['baseline']), []), [])
                    await register(interaction, source, items)
                    channel.send.assert_awaited_once()


class YoutubeOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_includes_channel_name_and_survives_lookup_failure(self):
        from bot import list_alerts
        interaction = SimpleNamespace(
            channel=Mock(spec=discord.TextChannel), guild_id=1, channel_id=10,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))
        store = SimpleNamespace(channel=lambda *args: [
            dict(kind='youtube', source='A'), dict(kind='youtube', source='B')])
        with patch('bot.bot', SimpleNamespace(store=store)), patch(
                'bot.get_channel_name', side_effect=['테스트 채널', RuntimeError('offline')]):
            await list_alerts.callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        message = interaction.followup.send.call_args.args[0]
        self.assertIn('테스트 채널\nhttps://www.youtube.com/channel/A', message)
        self.assertIn('채널명 조회 실패\nhttps://www.youtube.com/channel/B', message)

    async def test_poll_ignores_legacy_subscriptions(self):
        client = NotificationBot()
        youtube_row = dict(kind='youtube', source='A')
        client.store = SimpleNamespace(all=lambda: [youtube_row, dict(kind='legacy', source='B')])
        with patch('bot.get_videos', return_value=[{'id': 'new'}]) as loader, patch.object(
                client, 'deliver', new_callable=AsyncMock) as deliver:
            await client.poll()
        loader.assert_called_once_with('A')
        deliver.assert_awaited_once_with(youtube_row, [{'id': 'new'}])

    async def test_commands_use_youtube_prefix(self):
        from bot import bot
        self.assertEqual({command.name for command in bot.tree.get_commands()},
                         {'유튜브등록', '유튜브해제', '유튜브목록', '유튜브도움말', '유튜브핑'})
        command = bot.tree.get_command('유튜브해제')
        self.assertEqual([parameter.name for parameter in command.parameters], ['채널'])
        self.assertTrue(command.parameters[0].required)


class ChannelNameTests(unittest.TestCase):
    def test_channel_name_comes_from_feed_title(self):
        from youtube_checker import get_channel_name
        response = Mock(content=b'''<feed xmlns="http://www.w3.org/2005/Atom">
            <title>Example Channel</title></feed>''')
        with patch('youtube_checker.SESSION.get', return_value=response):
            self.assertEqual(get_channel_name('UC' + 'a' * 22), 'Example Channel')


if __name__ == '__main__':
    unittest.main()
