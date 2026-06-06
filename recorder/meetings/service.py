import asyncio
import datetime
import logging
from typing import Optional

import discord
from discord.ext import commands, voice_recv

from audio.sink import AudioSink
from meetings.state import (
    get_active_meeting,
    set_active_meeting,
    clear_active_meeting,
)

logger = logging.getLogger(__name__)


def is_real_active_meeting(meeting: dict | None) -> bool:
    if not meeting:
        return False

    vc = meeting.get("vc")
    sink = meeting.get("sink")

    return (
        vc is not None
        and sink is not None
        and hasattr(vc, "is_connected")
        and vc.is_connected()
    )

async def start_meeting_handler(
    ctx: commands.Context,
    *,
    save_meetings_fn,
    bot_loop,
    fail_meeting_capture_fn,
) -> None:
    """Join the caller's voice channel and start recording audio."""
    if ctx.author.voice is None:
        await ctx.send("❌ You must be in a voice channel to start a meeting.")
        return

    guild_id = ctx.guild.id

    existing_meeting = get_active_meeting(guild_id)

    if existing_meeting:
        if is_real_active_meeting(existing_meeting):
            await ctx.send("❌ A meeting is already active. Use `!end_meeting` to stop it first.")
            return

        logger.warning(
            f"[start_meeting] Stale meeting detected for guild {guild_id}; clearing state."
        )
        clear_active_meeting(guild_id)
        save_meetings_fn()

    try:
        voice_client = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
    except Exception as e:
        await ctx.send(f"❌ Failed to connect to voice channel: {e}")
        return

    meeting = {
        "channel": ctx.channel,
        "channel_id": ctx.channel.id,
        "vc": voice_client,
        "sink": None,
        "start_time": datetime.datetime.now(),
        "started_by": ctx.author.id,
        "mix_audio_path": None,
    }
    set_active_meeting(guild_id, meeting)

    sink = AudioSink(meeting)
    meeting["sink"] = sink

    def after_listen(err: Optional[Exception]) -> None:
        if err is None:
            return

        if isinstance(err, discord.opus.OpusError) and "corrupted stream" in str(err).lower():
            if bot_loop and not bot_loop.is_closed():
                bot_loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        fail_meeting_capture_fn(guild_id, meeting, str(err), ctx)
                    )
                )
        else:
            logger.error(f"[after_listen] Voice error: {err}")

    voice_client.listen(sink, after=after_listen)
    save_meetings_fn()

    await ctx.send(
        f"✅ **Meeting started!** Recording audio in `{ctx.author.voice.channel.name}`.\n"
        f"Use `!end_meeting` to stop and receive the audio file."
    )