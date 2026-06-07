import asyncio
import datetime
import logging
import os
from typing import Optional

import discord
from discord.ext import commands, voice_recv

from audio.sink import AudioSink
from audio.processing import compress_and_upload
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
                        fail_meeting_capture_handler(
                            guild_id,
                            meeting,
                            str(err),
                            save_meetings_fn=save_meetings_fn,
                            ctx=ctx,
                        )
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




async def end_meeting_handler(
    ctx: commands.Context,
    *,
    save_meetings_fn,
    process_meeting_in_minutes_api_fn,
    build_meeting_id_fn,
) -> None:
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
            try:
                await vc.disconnect()
            except Exception as e:
                logger.warning(f"[end_meeting_handler] Error disconnecting voice client: {e}")

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
                process_meeting_in_minutes_api_fn,
                guild_id,
                meeting,
                final_audio_path,
            )
            meeting_id = result.get("id") or build_meeting_id_fn(guild_id, meeting)
            meeting_type = result.get("tipo", "N/A")

            await ctx.send(
                f"✅ **Minutes generated successfully!**\n"
                f"🆔 Meeting ID: `{meeting_id}`\n"
                f"📝 Type: `{meeting_type}`"
            )
        except Exception as e:
            logger.error(f"[end_meeting_handler] Error calling minutes API: {e}")
            await ctx.send(
                f"⚠️ Audio recorded successfully, but failed to process minutes automatically.\n"
                f"Error: `{e}`"
            )

    except Exception as e:
        logger.error(f"[end_meeting_handler] Error: {e}")
        await ctx.send("❌ Error ending meeting. Please try again.")
    finally:
        clear_active_meeting(guild_id)
        save_meetings_fn()

async def meeting_status_handler(ctx: commands.Context) -> None:
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

async def auto_end_meeting_handler(
    guild_id: int,
    *,
    save_meetings_fn,
    process_meeting_in_minutes_api_fn,
    build_meeting_id_fn,
) -> None:
    """Disconnect, compress, upload audio, and process minutes automatically."""
    meeting = get_active_meeting(guild_id)
    if not meeting:
        return

    final_audio_path = None

    try:
        sink = meeting.get("sink")
        if sink and hasattr(sink, "cleanup"):
            sink.cleanup()

        vc = meeting.get("vc")
        if vc:
            try:
                await vc.disconnect()
            except Exception as e:
                logger.warning(
                    f"[auto_end_meeting_handler] Error disconnecting voice client for guild {guild_id}: {e}"
                )

        mix_path = meeting.get("mix_audio_path")
        channel = meeting.get("channel")
        duration = str(datetime.datetime.now() - meeting["start_time"]).split(".")[0]

        if channel:
            if mix_path and os.path.exists(mix_path):
                await channel.send(
                    "⏳ Everyone left — processing, uploading audio, and generating minutes..."
                )
                final_audio_path = await compress_and_upload(channel, mix_path, duration)

                if final_audio_path is None:
                    await channel.send(
                        "⚠️ Audio was recorded, but the converted OGG was invalid.\n"
                        "The audio was uploaded/saved, but automatic minute generation was skipped."
                    )
                    return

                try:
                    result = await asyncio.to_thread(
                        process_meeting_in_minutes_api_fn,
                        guild_id,
                        meeting,
                        final_audio_path,
                    )
                    meeting_id = result.get("id") or build_meeting_id_fn(guild_id, meeting)
                    meeting_type = result.get("tipo", "N/A")

                    await channel.send(
                        f"✅ **Minutes generated successfully!**\n"
                        f"🆔 Meeting ID: `{meeting_id}`\n"
                        f"📝 Type: `{meeting_type}`"
                    )
                except Exception as e:
                    logger.error(f"[auto_end_meeting_handler] Error calling minutes API: {e}")
                    await channel.send(
                        f"⚠️ Audio was recorded, but automatic minute generation failed.\n"
                        f"Error: `{e}`"
                    )
            else:
                await channel.send("🔇 Meeting ended automatically. Audio file not found.")

    except Exception as e:
        logger.error(f"[auto_end_meeting_handler] Error for guild {guild_id}: {e}")
    finally:
        clear_active_meeting(guild_id)
        save_meetings_fn()

async def fail_meeting_capture_handler(
    guild_id: int,
    meeting: dict,
    reason: str,
    *,
    save_meetings_fn,
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
        save_meetings_fn()        