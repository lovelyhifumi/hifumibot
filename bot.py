from discord.ext import tasks
from youtube_checker import get_latest_video, load_last_video, save_last_video
from config import DISCORD_CHANNEL_ID, CHECK_INTERVAL
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} 로그인 완료!")
    channel = bot.get_channel(1530184263406981180)
    if channel:
        await channel.send("✅ 봇이 정상적으로 시작되었습니다.")
    else:
        print("채널을 찾을 수 없습니다.")
    if not check_youtube.is_running():
        check_youtube.start()

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_youtube():
    video = get_latest_video()
    try:
        if video is None:
            return
        last_video = load_last_video()

    # 첫 실행이면 현재 영상 저장만 하고 알림 안 보냄
    # if last_video is None:
    #     save_last_video(video["id"])
    #     return

        if video["id"] != last_video:
            channel = await bot.fetch_channel(DISCORD_CHANNEL_ID)
            await channel.send(
                f"🔔 새 영상 업로드!\n{video['link']}"
         )
            save_last_video(video["id"])
    except Exception as e:
        print(f"유튜브 확인 중 오류: {e}")

bot.run(TOKEN)