"""여러 서버/채널용 슬래시 명령어 알림 봇. python bot.py로 실행."""
import asyncio
import json
import logging
import discord
from discord import app_commands
from discord.ext import tasks
from config import TOKEN, CHECK_INTERVAL, DATA_DIR, TEST_GUILD_ID
from subscriptions import SubscriptionStore, marker, pending_items
from youtube_checker import get_videos, resolve_channel, get_channel_name

log = logging.getLogger('notification_bot')


class NotificationBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.store = None
        self.lock = asyncio.Lock()
        self.history_cache = {}

    async def setup_hook(self):
        self.store = SubscriptionStore(DATA_DIR / 'subscriptions.sqlite3')
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.youtube_loop.start()

    async def close(self):
        self.youtube_loop.cancel()
        if self.store:
            self.store.close()
        await super().close()

    async def on_ready(self):
        log.info('%s 로그인 완료', self.user)

    async def on_guild_remove(self, guild):
        async with self.lock:
            removed_channels = {row['channel_id'] for row in self.store.all()
                                if row['guild_id'] == guild.id}
            self.store.remove_guild(guild.id)
            self.history_cache = {key: value for key, value in self.history_cache.items()
                                  if key[0] not in removed_channels}

    async def poll(self):
        async with self.lock:
            rows = [row for row in self.store.all() if row['kind'] == 'youtube']
            feeds = {}
            for source in dict.fromkeys(row['source'] for row in rows):
                try:
                    feeds[source] = await asyncio.to_thread(get_videos, source)
                except Exception as error:
                    # HTTP 응답 본문/키는 로그에 남기지 않습니다.
                    log.warning('유튜브 목록 조회 실패 (%s)', type(error).__name__)
            for row in rows:
                if row['source'] not in feeds:
                    continue
                try:
                    await self.deliver(row, feeds[row['source']])
                except Exception as error:
                    log.warning('채널 %s 알림 실패 (%s): 다음 주기에 재확인',
                                row['channel_id'], type(error).__name__)

    async def deliver(self, row, items):
        channel = self.get_channel(row['channel_id'])
        if channel is None:
            channel = await self.fetch_channel(row['channel_id'])
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != row['guild_id']:
            return
        require_bot_permissions(channel)
        key = (row['channel_id'], row['kind'], row['source'], row['anchor_id'])
        cached = self.history_cache.get(key)
        seen = set(cached['seen']) if cached else set()
        cursor = cached['cursor'] if cached else row['anchor_id']
        next_cursor = cursor
        prefix = marker(row['kind'], row['source'], '')
        # 일반 대화나 다른 알림이 끼어 있어도 이 구독의 모든 알림을 확인합니다.
        # 일부 기록만 읽고 발송하지 않도록 전체 조회 완료 후 전송합니다.
        async for message in channel.history(limit=None, after=discord.Object(id=cursor)):
            next_cursor = max(next_cursor, message.id)
            if message.author.id != self.user.id:
                continue
            for embed in message.embeds:
                footer = embed.footer.text or ''
                if footer.startswith(prefix):
                    seen.add(footer[len(prefix):])
        self.history_cache[key] = {'seen': seen, 'cursor': next_cursor}
        pending = pending_items(items, json.loads(row['baseline']), seen)
        for item in pending:
            embed = discord.Embed(title='🔔 새 영상',
                                  description=item['title'][:4000], url=item['url'],
                                  color=0xE53935)
            embed.add_field(name='바로가기', value=item['url'], inline=False)
            embed.set_footer(text=marker(row['kind'], row['source'], item['id']))
            await channel.send(embed=embed)
            seen.add(item['id'])

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def youtube_loop(self):
        await self.poll()

    @youtube_loop.before_loop
    async def before_youtube(self):
        await self.wait_until_ready()


bot = NotificationBot()


def require_bot_permissions(channel):
    perms = channel.permissions_for(channel.guild.me)
    needed = ('view_channel', 'send_messages', 'read_message_history', 'embed_links')
    missing = [name for name in needed if not getattr(perms, name)]
    if missing:
        raise ValueError('봇에 채널 보기·메시지 보내기·메시지 기록 보기·링크 삽입 권한이 필요합니다.')


def setting_channel(interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError('서버의 일반 텍스트 채널에서 사용해 주세요.')
    require_bot_permissions(interaction.channel)
    return interaction.channel


async def register(interaction, source, items):
    async with bot.lock:
        channel = setting_channel(interaction)
        for row in bot.store.channel(interaction.guild_id, channel.id):
            if row['kind'] == 'youtube' and row['source'] == source:
                await interaction.followup.send('이미 이 채널에 등록되어 있습니다.', ephemeral=True)
                return
        label = f'유튜브 https://www.youtube.com/channel/{source}'
        # 조회 함수는 오래된 항목부터 정렬하므로 마지막 항목이 최신입니다.
        latest = items[-1]
        preview = discord.Embed(
            title='🔎 등록 확인 · 최신 영상',
            description=latest['title'][:4000], url=latest['url'],
            color=0xE53935)
        preview.add_field(name='바로가기', value=latest['url'], inline=False)
        preview.set_footer(text='등록 시 조회한 최신 항목입니다. 이후 새 항목부터 자동으로 알립니다.')
        anchor = await channel.send(
            '✅ 알림 등록: ' + label + '\n최신 항목 한 건을 확인용으로 표시합니다. 이후 새 항목부터 알립니다.',
            embed=preview)
        try:
            bot.store.put(interaction.guild_id, channel.id, 'youtube', source, anchor.id, items)
        except Exception:
            await anchor.delete()
            raise
        await interaction.followup.send('이 채널을 알림 채널로 등록했습니다. /유튜브목록에서 확인할 수 있어요.', ephemeral=True)


@bot.tree.command(name='유튜브등록', description='현재 채널에 유튜브 새 영상 알림을 등록합니다')
@app_commands.guild_only()
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(채널='유튜브 채널 주소, @핸들 또는 UC로 시작하는 채널 ID')
async def youtube_register(interaction: discord.Interaction, 채널: str):
    setting_channel(interaction)
    await interaction.response.defer(ephemeral=True)
    source = await asyncio.to_thread(resolve_channel, 채널)
    items = await asyncio.to_thread(get_videos, source)
    await register(interaction, source, items)


@bot.tree.command(name='유튜브해제', description='현재 채널의 유튜브 영상 알림을 해제합니다')
@app_commands.guild_only()
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(채널='등록한 유튜브 채널 주소·@핸들·ID를 입력')
async def unregister(interaction: discord.Interaction, 채널: str):
    channel = setting_channel(interaction)
    await interaction.response.defer(ephemeral=True)
    source = await asyncio.to_thread(resolve_channel, 채널)
    async with bot.lock:
        removed = bot.store.remove(interaction.guild_id, channel.id, 'youtube', source)
        bot.history_cache = {key: value for key, value in bot.history_cache.items()
                             if key[:3] != (channel.id, 'youtube', source)}
    await interaction.followup.send('알림을 해제했습니다.' if removed else '일치하는 등록이 없습니다.', ephemeral=True)


@bot.tree.command(name='유튜브목록', description='현재 채널의 유튜브 구독을 확인합니다')
@app_commands.guild_only()
async def list_alerts(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError('일반 텍스트 채널에서 사용해 주세요.')
    rows = [row for row in bot.store.channel(interaction.guild_id, interaction.channel_id)
            if row['kind'] == 'youtube']
    await interaction.response.defer(ephemeral=True)
    lines = []
    for row in rows:
        source = row['source']
        try:
            name = await asyncio.to_thread(get_channel_name, source)
            name = discord.utils.escape_markdown(' '.join(name.split())[:80])
        except Exception as error:
            log.warning('유튜브 채널명 조회 실패 (%s)', type(error).__name__)
            name = '채널명 조회 실패'
        lines.append(f"🔔 {name}\nhttps://www.youtube.com/channel/{source}")
    # 등록이 많아도 Discord 메시지 길이 제한을 넘기지 않습니다.
    chunk = ''
    for line in lines:
        if chunk and len(chunk) + len(line) + 2 > 2000:
            await interaction.followup.send(chunk, ephemeral=True)
            chunk = ''
        chunk += ('\n\n' if chunk else '') + line
    if chunk:
        await interaction.followup.send(chunk, ephemeral=True)
    if not lines:
        await interaction.followup.send('이 채널에 등록된 알림이 없습니다.', ephemeral=True)


@bot.tree.command(name='유튜브도움말', description='유튜브 알림 봇 사용 방법을 확인합니다')
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        '알림을 받을 텍스트 채널에서 설정하세요.\n'
        '• `/유튜브등록 채널:@핸들` — 새 영상 알림\n'
        '• `/유튜브목록` — 현재 채널의 등록 확인\n'
        '• `/유튜브해제 채널:@핸들` — 선택한 유튜브 알림 해제\n'
        '설정 변경은 채널 관리 권한자만 가능합니다. 등록 시 최신 영상 한 건을 확인용으로 표시합니다.\n'
        '중복 확인을 위해 봇 알림 메시지는 삭제하지 마세요.', ephemeral=True)


@bot.tree.command(name='유튜브핑', description='봇 응답 상태를 확인합니다')
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message('🏓 Pong!', ephemeral=True)


@bot.tree.error
async def command_error(interaction, error):
    original = getattr(error, 'original', error)
    if isinstance(original, app_commands.MissingPermissions):
        message = '이 채널의 채널 관리 권한이 있어야 설정을 변경할 수 있습니다.'
    elif isinstance(original, app_commands.NoPrivateMessage):
        message = '서버의 텍스트 채널에서 사용해 주세요.'
    elif isinstance(original, ValueError):
        message = str(original)
    elif isinstance(original, discord.Forbidden):
        message = '봇의 채널 권한을 확인해 주세요: 채널 보기·메시지 보내기·기록 보기·링크 삽입.'
    else:
        log.warning('명령어 실패 (%s)', type(original).__name__)
        message = '처리하지 못했습니다. 잠시 후 다시 시도해 주세요. 계속 실패하면 봇 운영자에게 문의해 주세요.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        raise SystemExit('.env에 TOKEN을 설정해 주세요.')
    bot.run(TOKEN)
