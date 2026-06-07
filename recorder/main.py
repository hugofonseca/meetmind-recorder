import discord
from discord.ext import commands
import datetime
import os
import pickle
from dotenv import load_dotenv
import logging
from meetings.state import (
    get_active_meeting,
    set_active_meeting,
    clear_active_meeting,
    has_active_meeting,
    iter_active_meetings,
)
from meetings.service import (
    start_meeting_handler,
    end_meeting_handler,
    meeting_status_handler,
    auto_end_meeting_handler,
)
from meetings.persistence import (
    save_meetings as persist_save_meetings,
    load_meetings as persist_load_meetings,
)
from integrations.minutes_api import (
    build_meeting_id as integrations_build_meeting_id,
    process_meeting_in_minutes_api as integrations_process_meeting_in_minutes_api,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logging.getLogger("discord.ext.voice_recv").setLevel(logging.INFO)
logging.getLogger("discord.voice_state").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MEETINGS_FILE = "meetings.pkl"
MINUTES_API_URL = os.getenv("MINUTES_API_URL", "http://127.0.0.1:5000/process-meeting")
MINUTES_API_TIMEOUT = int(os.getenv("MINUTES_API_TIMEOUT", "180"))

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------------------------
# Persistence helpers (survive bot restarts)
# ---------------------------------------------------------------------------

def save_meetings() -> None:
    persist_save_meetings(MEETINGS_FILE)

def load_meetings() -> None:
    persist_load_meetings(MEETINGS_FILE)

# ---------------------------------------------------------------------------
# Helpers for integration with minutes API
# ---------------------------------------------------------------------------
def build_meeting_id(guild_id: int, meeting: dict) -> str:
    return integrations_build_meeting_id(guild_id, meeting)

def process_meeting_in_minutes_api(guild_id: int, meeting: dict, audio_path: str) -> dict:
    return integrations_process_meeting_in_minutes_api(
        guild_id,
        meeting,
        audio_path,
        base_url=MINUTES_API_URL,
        timeout=MINUTES_API_TIMEOUT,
        logger=logger,
    )
# ---------------------------------------------------------------------------
# Auto-end when everyone leaves the voice channel
# ---------------------------------------------------------------------------
async def auto_end_meeting(guild_id: int) -> None:
    await auto_end_meeting_handler(
        guild_id,
        save_meetings_fn=save_meetings,
        process_meeting_in_minutes_api_fn=process_meeting_in_minutes_api,
        build_meeting_id_fn=build_meeting_id,
    )
# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready() -> None:
    load_meetings()
    await restore_meeting_channels()
    logger.info(f"Logged in as {bot.user} | Guilds: {len(bot.guilds)}")
    print(f"✅ {bot.user} is online and ready.")

async def restore_meeting_channels() -> None:
    """Re-attach channel objects to meetings that survived a restart."""
    for guild_id, meeting in iter_active_meetings():
        guild = bot.get_guild(guild_id)
        if not guild:
            clear_active_meeting(guild_id)
            continue

        channel_id = meeting.get("channel_id")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                meeting["channel"] = channel
                logger.info(f"[restore] Channel restored for guild {guild_id}")
            else:
                logger.warning(f"[restore] Channel {channel_id} not found for guild {guild_id}")

@bot.event
async def on_voice_state_update(member, before, after) -> None:
    """Auto-end a meeting when the voice channel empties."""
    for guild_id, meeting in iter_active_meetings():
        vc = meeting.get("vc")
        if vc and vc.channel:
            human_members = [m for m in vc.channel.members if not m.bot]
            if not human_members:
                logger.info(f"[voice_state] Auto-ending meeting for guild {guild_id}")
                await auto_end_meeting(guild_id)
# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@bot.command(name="start_meeting", aliases=["start", "begin_meeting"])
async def start_meeting(ctx: commands.Context) -> None:
    await start_meeting_handler(
        ctx,
        save_meetings_fn=save_meetings,
        bot_loop=bot.loop,
    )

@bot.command(name="end_meeting", aliases=["end", "stop_meeting"])
async def end_meeting(ctx: commands.Context) -> None:
    await end_meeting_handler(
        ctx,
        save_meetings_fn=save_meetings,
        process_meeting_in_minutes_api_fn=process_meeting_in_minutes_api,
        build_meeting_id_fn=build_meeting_id,
    )

@bot.command(name="meeting_status", aliases=["status", "meeting_info"])
async def meeting_status(ctx: commands.Context) -> None:
    await meeting_status_handler(ctx)

@bot.command(name="restore_meeting", aliases=["restore", "recover_meeting"])
async def restore_meeting(ctx: commands.Context) -> None:
    """
    Restore meeting metadata from disk after a bot restart.

    Note: voice capture cannot be resumed — this only re-attaches the
    channel reference so you can see what was already recorded.
    """
    guild_id = ctx.guild.id

    if has_active_meeting(guild_id):
        await ctx.send("✅ A meeting is already active in this server.")
        return

    if not os.path.exists(MEETINGS_FILE):
        await ctx.send("❌ No saved meetings file found.")
        return

    try:
        with open(MEETINGS_FILE, "rb") as f:
            saved: dict = pickle.load(f)

        if guild_id not in saved:
            await ctx.send("❌ No saved meeting found for this server.")
            return

        data = saved[guild_id]
        age = (datetime.datetime.now() - data["start_time"]).total_seconds()
        if age > 86400:
            await ctx.send("❌ Saved meeting has expired (older than 24 hours).")
            return

        set_active_meeting(guild_id, {
            "channel": ctx.channel,
            "channel_id": ctx.channel.id,
            "vc": None,
            "sink": None,
            "start_time": data["start_time"],
            "started_by": data["started_by"],
            "mix_audio_path": data.get("mix_audio_path"),
        })

        mix_path = data.get("mix_audio_path") or "unknown"
        await ctx.send(
            f"✅ Meeting metadata restored.\n"
            f"🎙️ Audio file: `{mix_path}`\n"
            f"⚠️ Live recording cannot be resumed after a restart."
        )
        save_meetings()

    except Exception as e:
        await ctx.send(f"❌ Error restoring meeting: {e}")

@bot.command(name="fix_channel", aliases=["fix_ch", "repair_channel"])
async def fix_channel(ctx: commands.Context) -> None:
    """Point the active meeting's notification channel at the current channel."""
    guild_id = ctx.guild.id

    if not has_active_meeting(guild_id):
        await ctx.send("❌ No active meeting found in this server.")
        return

    meeting = get_active_meeting(guild_id)
    if meeting.get("channel") and meeting["channel"].id == ctx.channel.id:
        await ctx.send("✅ Channel reference is already correct.")
        return

    meeting["channel"] = ctx.channel
    meeting["channel_id"] = ctx.channel.id
    save_meetings()

    await ctx.send(
        f"✅ Notification channel updated to {ctx.channel.mention}.\n"
        f"`!end_meeting` will now upload the audio file here."
    )

@bot.command(name="meeting_help", aliases=["help_meeting"])
async def meeting_help(ctx: commands.Context) -> None:
    """Show all available commands."""
    embed = discord.Embed(
        title="🎙️ Meeting Audio Recorder — Help",
        description="Commands for recording and downloading voice channel audio",
        color=0x0099FF,
    )
    commands_info = [
        ("!start_meeting", "Join your voice channel and start recording audio."),
        ("!end_meeting", "Stop recording, upload audio, and generate minutes automatically."),
        ("!meeting_status", "Show whether a meeting is active and its duration."),
        ("!restore_meeting", "Re-attach metadata for a meeting lost after a restart."),
        ("!fix_channel", "Redirect meeting uploads to the current channel."),
        ("!meeting_help", "Show this help message."),
    ]
    for name, desc in commands_info:
        embed.add_field(name=name, value=desc, inline=False)

    embed.set_footer(text="Required bot permissions: Connect, Speak, Use Voice Activity, Attach Files")
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@bot.event
async def on_command_error(ctx: commands.Context, error) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument for `!{ctx.command.name}`.")
    else:
        logger.error(f"[on_command_error] {error}")
        await ctx.send(f"❌ An error occurred: {error}")
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set. Add it to your .env file.")
        raise SystemExit(1)

    print("🤖 Starting Discord Meeting Recorder...")
    print("   ✅ Audio recording (WAV)")
    print("   ✅ Auto-compress to OGG on end")
    print("   ✅ Auto-upload to Discord channel")
    print("   ✅ Auto-process minutes via API")
    print("   ✅ Auto-end when channel empties")
    print("   ✅ Restart-safe persistence")

    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        raise SystemExit(1)