import discord
from discord.ext import commands, voice_recv
import datetime
import os
import wave
import asyncio
import pickle
import ffmpeg
from typing import Optional
from dotenv import load_dotenv
import logging


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logging.getLogger("discord.ext.voice_recv").setLevel(logging.INFO)
logging.getLogger("discord.voice_state").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# guild_id -> meeting dict
active_meetings: dict = {}

MEETINGS_FILE = "meetings.pkl"


# ---------------------------------------------------------------------------
# Persistence helpers (survive bot restarts)
# ---------------------------------------------------------------------------
def save_meetings() -> None:
    """Persist serialisable meeting metadata to disk."""
    serialisable = {}
    for guild_id, meeting in active_meetings.items():
        serialisable[guild_id] = {
            "start_time":     meeting["start_time"],
            "started_by":     meeting["started_by"],
            "channel_id":     meeting.get("channel_id"),
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
            active_meetings[guild_id] = {
                "channel":        None,
                "channel_id":     data.get("channel_id"),
                "vc":             None,
                "sink":           None,
                "start_time":     data["start_time"],
                "started_by":     data["started_by"],
                "mix_audio_path": data.get("mix_audio_path"),
            }
        logger.info(f"[load_meetings] Loaded {len(saved)} meeting(s) from disk.")
    except Exception as e:
        logger.error(f"[load_meetings] Failed: {e}")


# ---------------------------------------------------------------------------
# Audio sink — captures PCM and writes a stereo 48 kHz WAV file
# ---------------------------------------------------------------------------
class AudioSink(voice_recv.AudioSink):
    """Writes every incoming voice packet to a single mixed WAV file."""

    def __init__(self, meeting: dict):
        super().__init__()
        self.stopped = False
        self.meeting = meeting

        os.makedirs("meeting_audio", exist_ok=True)
        timestamp = meeting["start_time"].strftime("%Y%m%d_%H%M%S")
        self.mix_path = os.path.join("meeting_audio", f"meeting_{timestamp}.wav")

        self.mix_wav = wave.open(self.mix_path, "wb")
        self.mix_wav.setnchannels(2)
        self.mix_wav.setsampwidth(2)
        self.mix_wav.setframerate(48000)

        meeting["mix_audio_path"] = self.mix_path
        logger.info(f"[AudioSink] Recording started: {self.mix_path}")

    # voice_recv protocol -------------------------------------------------

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        if self.stopped or not data.pcm or not user:
            return
        try:
            self.mix_wav.writeframes(data.pcm)
        except Exception as e:
            logger.error(f"[AudioSink] Write error: {e}")

    def cleanup(self) -> None:
        self.stopped = True
        try:
            if self.mix_wav:
                self.mix_wav.close()
                logger.info(f"[AudioSink] WAV closed: {self.mix_path}")
        except Exception as e:
            logger.error(f"[AudioSink] Cleanup error: {e}")


# ---------------------------------------------------------------------------
# Compress WAV → OGG and upload to Discord
# ---------------------------------------------------------------------------
async def compress_and_upload(
    channel: discord.TextChannel,
    wav_path: str,
    duration: str,
) -> None:
    """Convert WAV to OGG Opus and send as a Discord attachment.

    Falls back to the raw WAV if ffmpeg conversion fails.
    Handles Discord's 8 MB file-size limit gracefully.
    The OGG is deleted after upload; the WAV is kept as a local backup.
    """
    ogg_path = wav_path.replace(".wav", ".ogg")
    upload_path = wav_path  # default: raw WAV if compression fails

    # Compress ---------------------------------------------------------------
    try:
        (
            ffmpeg
            .input(wav_path)
            .output(ogg_path, acodec="libopus", ab="64k", ar=48000)
            .overwrite_output()
            .run(quiet=True)
        )
        upload_path = ogg_path
        logger.info(f"[compress_and_upload] OGG created: {ogg_path}")
    except Exception as e:
        logger.warning(f"[compress_and_upload] ffmpeg failed, falling back to WAV: {e}")

    # Upload -----------------------------------------------------------------
    try:
        filename = os.path.basename(upload_path)
        with open(upload_path, "rb") as f:
            await channel.send(
                f"✅ **Meeting ended!** ⏱️ Duration: {duration}\n"
                f"🎙️ Download your recording below:",
                file=discord.File(f, filename=filename),
            )
        logger.info(f"[compress_and_upload] Uploaded: {filename}")
    except discord.HTTPException as e:
        if e.status == 413:  # Payload Too Large
            await channel.send(
                f"✅ Meeting ended (duration: {duration}).\n"
                f"⚠️ Audio file too large to upload to Discord.\n"
                f"📁 Saved locally at: `{wav_path}`"
            )
            logger.warning(f"[compress_and_upload] File too large for Discord: {upload_path}")
        else:
            logger.error(f"[compress_and_upload] HTTP error uploading file: {e}")
            raise
    finally:
        # Always remove the OGG after upload attempt; keep WAV as local backup
        if os.path.exists(ogg_path):
            try:
                os.remove(ogg_path)
            except Exception as e:
                logger.warning(f"[compress_and_upload] Could not delete OGG: {e}")


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
        active_meetings.pop(guild_id, None)
        save_meetings()


# ---------------------------------------------------------------------------
# Auto-end when everyone leaves the voice channel
# ---------------------------------------------------------------------------
async def auto_end_meeting(guild_id: int) -> None:
    """Disconnect, compress, and upload the WAV when the last human leaves."""
    meeting = active_meetings.pop(guild_id, None)
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
                await channel.send("⏳ Everyone left — processing and uploading audio...")
                await compress_and_upload(channel, mix_path, duration)
            else:
                await channel.send("🔇 Meeting ended automatically. Audio file not found.")

    except Exception as e:
        logger.error(f"[auto_end_meeting] Error for guild {guild_id}: {e}")
    finally:
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
    for guild_id, meeting in list(active_meetings.items()):
        guild = bot.get_guild(guild_id)
        if not guild:
            active_meetings.pop(guild_id, None)
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
    for guild_id, meeting in list(active_meetings.items()):
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
    """Join the caller's voice channel and start recording audio."""
    if ctx.author.voice is None:
        await ctx.send("❌ You must be in a voice channel to start a meeting.")
        return

    guild_id = ctx.guild.id

    if guild_id in active_meetings:
        await ctx.send("❌ A meeting is already active. Use `!end_meeting` to stop it first.")
        return

    try:
        voice_client = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
    except Exception as e:
        await ctx.send(f"❌ Failed to connect to voice channel: {e}")
        return

    meeting = {
        "channel":        ctx.channel,
        "channel_id":     ctx.channel.id,
        "vc":             voice_client,
        "sink":           None,
        "start_time":     datetime.datetime.now(),
        "started_by":     ctx.author.id,
        "mix_audio_path": None,
    }
    active_meetings[guild_id] = meeting

    sink = AudioSink(meeting)
    meeting["sink"] = sink

    def after_listen(err: Optional[Exception]) -> None:
        if err is None:
            return
        if isinstance(err, discord.opus.OpusError) and "corrupted stream" in str(err).lower():
            loop = bot.loop
            if loop and not loop.is_closed():
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        fail_meeting_capture(guild_id, meeting, str(err), ctx)
                    )
                )
        else:
            logger.error(f"[after_listen] Voice error: {err}")

    voice_client.listen(sink, after=after_listen)
    save_meetings()

    await ctx.send(
        f"✅ **Meeting started!** Recording audio in `{ctx.author.voice.channel.name}`.\n"
        f"Use `!end_meeting` to stop and receive the audio file."
    )


@bot.command(name="end_meeting", aliases=["end", "stop_meeting"])
async def end_meeting(ctx: commands.Context) -> None:
    """Stop recording, compress the audio, and upload it to this channel."""
    guild_id = ctx.guild.id

    if guild_id not in active_meetings:
        await ctx.send("❌ No active meeting found in this server.")
        return

    meeting = active_meetings.pop(guild_id)

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
            await ctx.send("⏳ Processing and uploading audio...")
            await compress_and_upload(ctx.channel, mix_path, duration)
        else:
            await ctx.send(f"✅ Meeting ended (duration: {duration}). Audio file not found.")

    except Exception as e:
        logger.error(f"[end_meeting] Error: {e}")
        await ctx.send("❌ Error ending meeting. Please try again.")
    finally:
        save_meetings()


@bot.command(name="meeting_status", aliases=["status", "meeting_info"])
async def meeting_status(ctx: commands.Context) -> None:
    """Show whether a meeting is currently active and how long it has been running."""
    guild_id = ctx.guild.id

    if guild_id in active_meetings:
        meeting = active_meetings[guild_id]
        duration = str(datetime.datetime.now() - meeting["start_time"]).split(".")[0]

        embed = discord.Embed(title="🎙️ Active Meeting", color=0x00FF00)
        embed.add_field(name="Status",     value="🟢 **RECORDING**",            inline=True)
        embed.add_field(name="Duration",   value=f"⏱️ {duration}",              inline=True)
        embed.add_field(name="Started by", value=f"<@{meeting['started_by']}>", inline=True)

        mix_path = meeting.get("mix_audio_path") or "pending…"
        embed.add_field(name="Audio file", value=f"`{mix_path}`", inline=False)
        embed.set_footer(text="Use !end_meeting to stop and receive the audio file.")
        await ctx.send(embed=embed)
    else:
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


@bot.command(name="restore_meeting", aliases=["restore", "recover_meeting"])
async def restore_meeting(ctx: commands.Context) -> None:
    """Restore meeting metadata from disk after a bot restart.

    Note: voice capture cannot be resumed — this only re-attaches the
    channel reference so you can see what was already recorded.
    """
    guild_id = ctx.guild.id

    if guild_id in active_meetings:
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

        active_meetings[guild_id] = {
            "channel":        ctx.channel,
            "channel_id":     ctx.channel.id,
            "vc":             None,
            "sink":           None,
            "start_time":     data["start_time"],
            "started_by":     data["started_by"],
            "mix_audio_path": data.get("mix_audio_path"),
        }

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

    if guild_id not in active_meetings:
        await ctx.send("❌ No active meeting found in this server.")
        return

    meeting = active_meetings[guild_id]
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
        ("!start_meeting",   "Join your voice channel and start recording audio."),
        ("!end_meeting",     "Stop recording and receive the audio file as a download."),
        ("!meeting_status",  "Show whether a meeting is active and its duration."),
        ("!restore_meeting", "Re-attach metadata for a meeting lost after a restart."),
        ("!fix_channel",     "Redirect meeting uploads to the current channel."),
        ("!meeting_help",    "Show this help message."),
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
    print("   ✅ Auto-end when channel empties")
    print("   ✅ Restart-safe persistence")

    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        raise SystemExit(1)
