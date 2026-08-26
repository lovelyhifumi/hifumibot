import os
import requests
from dotenv import load_dotenv
load_dotenv()
from discord.ext import tasks
from config import DISCORD_MALGEUM_ID, DISCORD_CHAT_ID, DISCORD_NOTICE_ID, CHECK_INTERVAL
from youtube_checker import get_latest_video, load_last_video, save_last_video
from maplenotice_checker import get_notices, save_last_notice, load_last_notice

import discord
from discord.ext import commands


TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
alert_channel = None
yt_alert_channel = None
notice_channel = None
@bot.event
async def on_ready():
    global alert_channel, yt_alert_channel, notice_channel
    print(f"{bot.user} 로그인 완료!")
    try:
        alert_channel = await bot.fetch_channel(DISCORD_CHAT_ID)
        yt_alert_channel = await bot.fetch_channel(DISCORD_MALGEUM_ID)
        notice_channel = await bot.fetch_channel(DISCORD_NOTICE_ID)
        await alert_channel.send("✅ 봇이 정상적으로 시작되었습니다.")
    except Exception as e:
        print(f"채널을 찾을 수 없습니다. : {e}")
        return
    if not check_youtube.is_running():
        check_youtube.start()
    if not check_nexon.is_running():
        check_nexon.start()

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_youtube():
    try:
        video = get_latest_video()

        if video is None:
            return

        last_video = load_last_video()

        print("현재 유튜브 영상 ID:", video["id"])
        print("저장된 영상 ID:", last_video)

        if last_video is None:
            save_last_video(video["id"])
            print("첫 실행: 최신 영상 저장")
            return

        if video["id"] != last_video:
            await yt_alert_channel.send(
                f"🔔 새 영상 업로드!\n{video['link']}"
            )

            save_last_video(video["id"])

    except Exception as e:
        print(f"유튜브 확인 중 오류: {e}")

@tasks.loop(seconds=CHECK_INTERVAL * 5)
async def check_nexon():
    notices = get_notices()
    if notices is None:
        return
    last_notice_id = load_last_notice()
    if last_notice_id is None:
        print("최초 실행 감지")
        print("저장할 공지 ID:", notices[0]["notice_id"])
        save_last_notice(notices[0]["notice_id"])
        print("저장 완료")
        return
    print("현재 최신 공지 ID:", notices[0]["notice_id"])

    new_notices = []
    for notice in notices:
        if notice["notice_id"] == last_notice_id:
            break
        new_notices.append(notice)
    new_notices.reverse()

    for notice in new_notices:
        await notice_channel.send(
            f"🍁 **새 공지사항**\n"
            f"{notice['title']}\n"
            f"{notice['url']}"
        )
    save_last_notice(notices[0]["notice_id"])

bot.run(TOKEN)