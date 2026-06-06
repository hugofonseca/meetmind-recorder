import discord
from discord.ext import commands, voice_recv
import datetime
import os
import asyncio
import pickle
import requests
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import logging
from audio.sink import AudioSink
from audio.processing import compress_and_upload
from meetings.state import (
    get_active_meeting,
    set_active_meeting,
    clear_active_meeting,
    has_active_meeting,
    iter_active_meetings,
    clear_all_active_meetings
)
from meetings.service import start_meeting_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Persist serialisable meeting metadata to disk."""
    serialisable = {}
    for guild_id, meeting in iter_active_meetings():
        serialisable[guild_id] = {
            "start_time": meeting["start_time"],
            "started_by": meeting["started_by"],
            "channel_id": meeting.get("channel_id"),
            "mix_audio_path": meeting.get("mix_audio_path"),
        }
    try:
        with open(MEETINGS_FILE, "wb") as f:
            pickle.dump(serialisable, f)
    except Exception as e:
        logger.error(f"[save_meetings] Failed: {e}")

def load_meetings() -> None:
    """Load persisted meeting metadata on startup."""
    if not os.path.exists(MEETINGS_FILE):
        return
    try:
        with open(MEETINGS_FILE, "rb") as f:
            saved: dict = pickle.load(f)

        for guild_id, data in saved.items():
            set_active_meeting(guild_id, {
                "channel": None,
                "channel_id": data.get("channel_id"),
                "vc": None,
                "sink": None,
                "start_time": data["start_time"],
                "started_by": data["started_by"],
                "mix_audio_path": data.get("mix_audio_path"),
            })

        logger.info(f"[load_meetings] Loaded {len(saved)} meeting(s) from disk.")
    except Exception as e:
        logger.error(f"[load_meetings] Failed: {e}")


# ---------------------------------------------------------------------------
# Helpers for integration with minutes API
# ---------------------------------------------------------------------------
def sanitize_meeting_id(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "meeting"


def build_meeting_id(guild_id: int, meeting: dict) -> str:
    start_time = meeting.get("start_time")
    started_by = meeting.get("started_by", "unknown")
    timestamp = (
        start_time.strftime("%Y%m%d_%H%M%S")
        if start_time
        else datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    return sanitize_meeting_id(f"guild_{guild_id}_{started_by}_{timestamp}")


def process_meeting_in_minutes_api(guild_id: int, meeting: dict, audio_path: str) -> dict:
    meeting_id = build_meeting_id(guild_id, meeting)

    payload = {
        "meeting_id": meeting_id,
        "audio_path": str(Path(audio_path).resolve()),
    }

    logger.info(f"[minutes_api] Sending payload: {payload}")

    endpoint = f"{MINUTES_API_URL.rstrip('/')}/process-meeting"

    response = requests.post(
        endpoint,
        json=payload,
        timeout=MINUTES_API_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()

# ---------------------------------------------------------------------------
# Fallback handler — corrupted Opus stream
# ---------------------------------------------------------------------------
async def fail_meeting_capture(
    guild_id: int,
    meeting: dict,
    reason: str,
    ctx: Optional[commands.Context] = None,
) -> None:
    """Tear down a meeting that failed due to a bad audio stream."""
    try:
        sink = meeting.get("sink")
        if sink and hasattr(sink, "cleanup"):
            sink.cleanup()

        vc = meeting.get("vc")
        if vc:
            if hasattr(vc, "is_listening") and vc.is_listening():
                try:
                    vc.stop_listening()
                except Exception:
                    pass
            try:
                await vc.disconnect()
            except Exception:
                pass

        msg = (
            "⚠️ **Audio capture failed (corrupted Opus stream).**\n"
            "✅ For stable recording, use a **Stage Channel**.\n"
            "➡️ Join the Stage and run `!start_meeting` again.\n"
        )

        channel = meeting.get("channel")
        if channel:
            try:
                await channel.send(msg)
            except Exception:
                pass

        if ctx and ctx.channel and (not channel or ctx.channel.id != channel.id):
            try:
                await ctx.send(msg)
            except Exception:
                pass

    finally:
        clear_active_meeting(guild_id)
        save_meetings()


# ---------------------------------------------------------------------------
# Auto-end when everyone leaves the voice channel
# ---------------------------------------------------------------------------
async def auto_end_meeting(guild_id: int) -> None:
    """Disconnect, compress, upload audio, and process minutes automatically."""
    meeting = clear_active_meeting(guild_id)
    if not meeting:
        return

    try:
        sink = meeting.get("sink")
        if sink and hasattr(sink, "cleanup"):
            sink.cleanup()

        vc = meeting.get("vc")
        if vc:
            await vc.disconnect()

        mix_path = meeting.get("mix_audio_path")
        channel = meeting.get("channel")
        duration = str(datetime.datetime.now() - meeting["start_time"]).split(".")[0]

        if channel:
            if mix_path and os.path.exists(mix_path):
                await channel.send("⏳ Everyone left — processing, uploading audio, and generating minutes...")
                final_audio_path = await compress_and_upload(channel, mix_path, duration)

                try:
                    result = await asyncio.to_thread(
                        process_meeting_in_minutes_api,
                        guild_id,
                        meeting,
                        final_audio_path,
                    )
                    meeting_id = result.get("id") or build_meeting_id(guild_id, meeting)
                    meeting_type = result.get("tipo", "N/A")

                    await channel.send(
                        f"✅ **Minutes generated successfully!**\n"
                        f"🆔 Meeting ID: `{meeting_id}`\n"
                        f"📝 Type: `{meeting_type}`"
                    )
                except Exception as e:
                    logger.error(f"[auto_end_meeting] Error calling minutes API: {e}")
                    await channel.send(
                        f"⚠️ Audio was recorded, but automatic minute generation failed.\n"
                        f"Error: `{e}`"
                    )
            else:
                await channel.send("🔇 Meeting ended automatically. Audio file not found.")

    except Exception as e:
        logger.error(f"[auto_end_meeting] Error for guild {guild_id}: {e}")
    finally:
        clear_active_meeting(guild_id)
        save_meetings()


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
        fail_meeting_capture_fn=fail_meeting_capture,
    )


@bot.command(name="end_meeting", aliases=["end", "stop_meeting"])
async def end_meeting(ctx: commands.Context) -> None:
    """Stop recording, upload audio, and process minutes automatically."""
    guild_id = ctx.guild.id
    meeting = get_active_meeting(guild_id)

    if not meeting:
        await ctx.send("❌ No active meeting found in this server.")
        return

    final_audio_path = None

    try:
        sink = meeting.get("sink")
        if sink and hasattr(sink, "cleanup"):
            sink.cleanup()

        vc = meeting.get("vc")
        if vc:
            await vc.disconnect()

        mix_path = meeting.get("mix_audio_path")
        duration = str(datetime.datetime.now() - meeting["start_time"]).split(".")[0]

        if mix_path and os.path.exists(mix_path):
            await ctx.send("⏳ Processing, uploading audio, and generating minutes...")
            final_audio_path = await compress_and_upload(ctx.channel, mix_path, duration)
        else:
            await ctx.send(
                "⚠️ Meeting was stopped, but no audio file was found to process."
            )
            return

        if final_audio_path is None:
            await ctx.send(
                "⚠️ Audio recorded successfully, but the converted OGG was invalid.\n"
                "The audio was uploaded/saved, but automatic minutes generation was skipped."
            )
            return

        try:
            result = await asyncio.to_thread(
                process_meeting_in_minutes_api,
                guild_id,
                meeting,
                final_audio_path,
            )
            meeting_id = result.get("id") or build_meeting_id(guild_id, meeting)
            meeting_type = result.get("tipo", "N/A")

            await ctx.send(
                f"✅ **Minutes generated successfully!**\n"
                f"🆔 Meeting ID: `{meeting_id}`\n"
                f"📝 Type: `{meeting_type}`"
            )
        except Exception as e:
            logger.error(f"[end_meeting] Error calling minutes API: {e}")
            await ctx.send(
                f"⚠️ Audio recorded successfully, but failed to process minutes automatically.\n"
                f"Error: `{e}`"
            )

    except Exception as e:
        logger.error(f"[end_meeting] Error: {e}")
        await ctx.send("❌ Error ending meeting. Please try again.")
    finally:
        clear_active_meeting(guild_id)
        save_meetings()


@bot.command(name="meeting_status", aliases=["status", "meeting_info"])
async def meeting_status(ctx: commands.Context) -> None:
    """Show whether a meeting is currently active and how long it has been running."""
    guild_id = ctx.guild.id
    meeting = get_active_meeting(guild_id)

    if not meeting:
        embed = discord.Embed(
            title="🎙️ Meeting Status",
            description="No active meeting in this server.",
            color=0xFF0000,
        )
        embed.add_field(
            name="Start one",
            value="Join a voice channel, then run `!start_meeting`.",
            inline=False,
        )
        await ctx.send(embed=embed)
        return

    duration = str(datetime.datetime.now() - meeting["start_time"]).split(".")[0]

    embed = discord.Embed(title="🎙️ Active Meeting", color=0x00FF00)
    embed.add_field(name="Status", value="🟢 **RECORDING**", inline=True)
    embed.add_field(name="Duration", value=f"⏱️ {duration}", inline=True)
    embed.add_field(name="Started by", value=f"<@{meeting['started_by']}>", inline=True)

    mix_path = meeting.get("mix_audio_path") or "pending…"
    embed.add_field(name="Audio file", value=f"`{mix_path}`", inline=False)
    embed.set_footer(text="Use !end_meeting to stop and receive the audio file.")
    await ctx.send(embed=embed)


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