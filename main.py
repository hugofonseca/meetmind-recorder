import discord
import datetime as dt
import os
import json
import wave
import asyncio
import pickle
import ffmpeg
import platform
import sys
import subprocess
import logging
from typing import Optional
from discord.ext import commands, voice_recv
from dotenv import load_dotenv




from pathlib import Path

BASE_DIR = Path("meeting_audio")

def create_meeting_structure(start_time: dt.datetime) -> tuple[str, str]:
    meeting_id = start_time.strftime("%Y%m%d_%H%M%S")
    meeting_dir = BASE_DIR / "meetings" / meeting_id

    (meeting_dir / "audio").mkdir(parents=True, exist_ok=True)
    (meeting_dir / "events").mkdir(parents=True, exist_ok=True)
    (meeting_dir / "chunks").mkdir(parents=True, exist_ok=True)  # opcional p/ futuro

    # retornando strings (melhor p/ pickle/serialização)
    return meeting_id, str(meeting_dir)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logging.getLogger("discord.ext.voice_recv").setLevel(logging.INFO)
logging.getLogger("discord.voice_state").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ---------------------------------------------------------------------------
# Manifest schema
# ---------------------------------------------------------------------------
MANIFEST_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Audio encoding config (master raw.ogg)
# ---------------------------------------------------------------------------
RAW_OPUS_TARGET_KBPS = 96           # alvo do bitrate do raw.ogg (alta qualidade)
RAW_OPUS_VBR = True                 # você está usando VBR
RAW_OPUS_APPLICATION = "voip"       # você está usando -application voip
RAW_CONTAINER = "ogg"
RAW_CODEC = "opus"

# ---------------------------------------------------------------------------
# Debug flags
# ---------------------------------------------------------------------------
INCLUDE_DEBUG_PATHS = False  # deixe False por padrão (evita expor paths absolutos)


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
            "start_time": meeting["start_time"],
            "started_by": meeting["started_by"],
            "channel_id": meeting.get("channel_id"),
            "meeting_id": meeting.get("meeting_id"),
            "meeting_dir": meeting.get("meeting_dir"),
            "raw_audio_path": meeting.get("raw_audio_path"),
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
            start_time = data["start_time"]
            if isinstance(start_time, dt.datetime) and start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=dt.timezone.utc)

            # ✅ migração: se raw_audio_path não existir no pkl antigo, usa mix_audio_path
            raw_audio_path = data.get("raw_audio_path") or data.get("mix_audio_path")

            active_meetings[guild_id] = {
                "channel":        None,
                "channel_id":     data.get("channel_id"),
                "vc":             None,
                "sink":           None,
                "start_time":     start_time,
                "started_by":     data["started_by"],
                "meeting_id":     data.get("meeting_id"),
                "meeting_dir":    data.get("meeting_dir"),
                "raw_audio_path": raw_audio_path,  # ✅ só raw no runtime
            }

        logger.info(f"[load_meetings] Loaded {len(saved)} meeting(s) from disk.")
    except Exception as e:
        logger.error(f"[load_meetings] Failed: {e}")


# ---------------------------------------------------------------------------
# Audio sink ogg
# ---------------------------------------------------------------------------
class AudioSinkOgg(voice_recv.AudioSink):
    """Recebe PCM e grava diretamente em OGG/Opus (qualidade alta) via FFmpeg."""

    def __init__(self, meeting: dict):
        super().__init__()
        self.stopped = False
        self.meeting = meeting

        meeting["bitrate_target_kbps"] = RAW_OPUS_TARGET_KBPS        
        meeting["encoding_application"] = RAW_OPUS_APPLICATION
        meeting["encoding_vbr"] = RAW_OPUS_VBR
        meeting["capture_started_at_dt"] = utc_now_dt()
        meeting["capture_started_at"] = to_utc_z(meeting["capture_started_at_dt"])

        ogg_path = meeting["raw_audio_path"]
        os.makedirs(os.path.dirname(ogg_path), exist_ok=True)

        # PCM vindo do voice_recv é compatível com o WAV atual: s16le, 48kHz, 2 canais.
        # Como é reunião mesclada, fazemos downmix para MONO e usamos bitrate ALTO (96k).
        cmd = [
            "ffmpeg", "-y",
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "-i", "pipe:0",

            "-ac", "1",                  # ✅ downmix mono (ideal p/ reunião mesclada)
            "-c:a", "libopus",
            "-b:a", f"{RAW_OPUS_TARGET_KBPS}k",  # ✅ usando a constante
            "-vbr", "on",
            "-application", RAW_OPUS_APPLICATION,

            ogg_path
        ]

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        logger.info(f"[AudioSinkOgg] Recording started: {ogg_path}")

    def wants_opus(self) -> bool:
        return False  # queremos PCM

    def write(self, user, data: voice_recv.VoiceData) -> None:
        if self.stopped or not data.pcm or not user:
            return
        try:
            if self.proc and self.proc.stdin:
                self.proc.stdin.write(data.pcm)
        except BrokenPipeError:
            logger.error("[AudioSinkOgg] FFmpeg pipe closed unexpectedly.")
            self.stopped = True
        except Exception as e:
            logger.error(f"[AudioSinkOgg] Write error: {e}")


    def cleanup(self) -> None:
        self.stopped = True
        try:
            if self.proc and self.proc.stdin:
                self.proc.stdin.close()
            if self.proc:
                self.proc.wait(timeout=10)
            self.meeting["capture_ended_at_dt"] = utc_now_dt()
            self.meeting["capture_ended_at"] = to_utc_z(self.meeting["capture_ended_at_dt"])
            self.meeting["capture_duration_sec"] = (
                self.meeting["capture_ended_at_dt"] - self.meeting["capture_started_at_dt"]
            ).total_seconds()


            logger.info(f"[AudioSinkOgg] OGG closed: {self.meeting.get('raw_audio_path')}")
        except Exception as e:
            logger.error(f"[AudioSinkOgg] Cleanup error: {e}")
            try:
                if self.proc:
                    self.proc.terminate()
            except Exception:
                pass


def format_hms(seconds: float) -> str:
    """Converte segundos para HH:MM:SS (arredondando para o segundo mais próximo)."""
    if seconds is None:
        return None
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def utc_now_dt() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def to_utc_z(dt_value: dt.datetime) -> str:
    """Converte datetime para ISO8601 em UTC com sufixo Z."""
    if dt_value is None:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=dt.timezone.utc)
    else:
        dt_value = dt_value.astimezone(dt.timezone.utc)
    return dt_value.isoformat().replace("+00:00", "Z")

def utc_now_z() -> str:
    return utc_now_dt().isoformat().replace("+00:00", "Z")

def ffprobe_format_info(path: str) -> dict:
    """
    Retorna JSON do ffprobe contendo 'format' e 'streams' do arquivo.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    return json.loads(out)

def probe_audio_info(path: str) -> dict:
    """
    Extrai metadados úteis do áudio:
    - duration_sec
    - bitrate_bps (preferência: format.bit_rate; fallback: size/duration)
    - codec, channels, sample_rate_hz, size_bytes
    """
    info = {
        "duration_sec": None,
        "duration_hms": None,
        "bitrate_bps": None,
        "bitrate_kbps": None,
        "codec": None,
        "channels": None,
        "sample_rate_hz": None,
        "size_bytes": None,
    }

    if not path or not os.path.exists(path):
        return info

    info["size_bytes"] = os.path.getsize(path)

    try:
        data = ffprobe_format_info(path)

        fmt = data.get("format") or {}
        streams = data.get("streams") or []

        # Duração (segundos)
        dur = fmt.get("duration")
        if dur is not None:
            info["duration_sec"] = float(dur)
        
        if info["duration_sec"] is not None:
            info["duration_hms"] = format_hms(info["duration_sec"])
        else:
            info["duration_hms"] = None

        # Bitrate no nível do container (pode existir mesmo quando stream.bit_rate é N/A)
        br = fmt.get("bit_rate")
        if br is not None:
            try:
                info["bitrate_bps"] = int(br)
            except Exception:
                pass

        # Pegar stream de áudio principal
        audio_stream = None
        for s in streams:
            if (s.get("codec_type") == "audio"):
                audio_stream = s
                break

        if audio_stream:
            info["codec"] = audio_stream.get("codec_name")
            ch = audio_stream.get("channels")
            if ch is not None:
                info["channels"] = int(ch)

            sr = audio_stream.get("sample_rate")
            if sr is not None:
                try:
                    info["sample_rate_hz"] = int(sr)
                except Exception:
                    pass

        # Fallback: bitrate médio calculado (size_bytes * 8 / duration_sec)
        if info["bitrate_bps"] is None and info["duration_sec"]:
            info["bitrate_bps"] = int((info["size_bytes"] * 8) / info["duration_sec"])

        if info["bitrate_bps"] is not None:
            info["bitrate_kbps"] = round(info["bitrate_bps"] / 1000, 1)

        return info

    except Exception as e:
        # Se o ffprobe falhar, ainda dá para calcular bitrate médio se tiver duração depois (mas aqui faltará duração)
        logger.warning(f"[probe_audio_info] ffprobe failed for {path}: {e}")
        return info

def get_git_commit_short() -> str | None:
    """Retorna commit curto do git (se repo tiver git disponível)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
        return out or None
    except Exception:
        return None

def get_recorder_info() -> dict:
    """Metadados do serviço recorder para rastreabilidade."""
    return {
        "service": "meetmind-recorder",
        "git_commit": get_git_commit_short(),
        "host": platform.node(),
        "python": sys.version.split()[0],
        "timestamp_utc": utc_now_z(),
    }

def create_manifest(meeting: dict, audio_info: dict) -> None:
    """Cria manifest.json dentro da pasta da reunião, incluindo auditoria e rastreabilidade."""
    meeting_dir = meeting["meeting_dir"]

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,  # ✅ NOVO
        "meeting_id": meeting["meeting_id"],
        "created_at": to_utc_z(meeting["start_time"]),
        "started_at": to_utc_z(meeting["start_time"]),
        "ended_at": meeting.get("ended_at"),
        "source": "discord",
        "audio": {
            "raw": "audio/raw.ogg",

            # ----- medidos via ffprobe / cálculo -----
            "duration_sec": audio_info.get("duration_sec"),
            "duration_hms": audio_info.get("duration_hms"),
            "bitrate_bps": audio_info.get("bitrate_bps"),
            "bitrate_kbps": audio_info.get("bitrate_kbps"),
            "size_bytes": audio_info.get("size_bytes"),
            "codec": audio_info.get("codec"),
            "channels": audio_info.get("channels"),
            "sample_rate_hz": audio_info.get("sample_rate_hz"),

            # ----- configurado (auditoria) -----
            "bitrate_target_kbps": meeting.get("bitrate_target_kbps", RAW_OPUS_TARGET_KBPS),

            "capture_started_at": meeting.get("capture_started_at"),
            "capture_ended_at": meeting.get("capture_ended_at"),
            "capture_duration_sec": meeting.get("capture_duration_sec"),

            # ✅ NOVO: como o áudio foi gerado
            "encoding": {
                "container": RAW_CONTAINER,
                "codec": RAW_CODEC,
                "vbr": meeting.get("encoding_vbr", RAW_OPUS_VBR),
                "application": meeting.get("encoding_application", RAW_OPUS_APPLICATION),
                "bitrate_target_kbps": meeting.get("bitrate_target_kbps", RAW_OPUS_TARGET_KBPS),
            },
        },

        # ✅ NOVO: rastreabilidade do recorder
        "recorder": get_recorder_info(),

        "status": {
            "audio_ready": True,
            "transcription_ready": False,
            "llm_processed": False
        }
    }

    path = os.path.join(meeting_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def emit_audio_ready(meeting: dict) -> None:
    """Emite um evento local para sinalizar que a transcrição pode começar."""
    meeting_dir = meeting["meeting_dir"]

    event = {
        "event": "audio_ready",
        "meeting_id": meeting["meeting_id"],
        "manifest": "manifest.json"
    }

    path = os.path.join(meeting_dir, "events", "audio_ready.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(event, f, indent=2, ensure_ascii=False)

def finalize_meeting_files(meeting: dict) -> None:
    """Finaliza o pacote da reunião (manifest + evento), enriquecendo com duração e bitrate médio."""
    
    raw_path = meeting.get("raw_audio_path")

    audio_info = probe_audio_info(raw_path) if raw_path else {}

    create_manifest(meeting, audio_info)
    emit_audio_ready(meeting)


'''
def finalize_meeting_files(meeting: dict) -> None:
    """Finaliza o pacote da reunião (manifest + evento)."""
    create_manifest(meeting)
    emit_audio_ready(meeting)

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
'''

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


        ended_dt = utc_now_dt()  # aware UTC
        meeting["ended_at"] = ended_dt.isoformat().replace("+00:00", "Z")
        duration = str(ended_dt - meeting["start_time"])


        audio_path = meeting.get("raw_audio_path")

        channel = meeting.get("channel")
        if channel:
            if audio_path and os.path.exists(audio_path):
                finalize_meeting_files(meeting)
                await channel.send(
                    f"🔇 Everyone left — meeting ended (duration: {duration}).\n"
                    f"📁 Áudio salvo localmente.\n"
                    f"🧾 Manifest gerado."
                )
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
        "start_time": utc_now_dt(),
        "started_by":     ctx.author.id,
    }
    active_meetings[guild_id] = meeting

    meeting_id, meeting_dir = create_meeting_structure(meeting["start_time"])

    meeting["meeting_id"] = meeting_id
    meeting["meeting_dir"] = meeting_dir
    meeting["raw_audio_path"] = os.path.join(meeting_dir, "audio", "raw.ogg")

    sink = AudioSinkOgg(meeting)
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

        meeting["ended_at"] = utc_now_z()

        audio_path = meeting.get("raw_audio_path")
        duration = str(utc_now_dt() - meeting["start_time"]).split(".")[0]

        if audio_path and os.path.exists(audio_path):
            finalize_meeting_files(meeting)
            await ctx.send(
                f"✅ Meeting ended (duration: {duration}).\n"
                f"📁 Áudio salvo localmente em: `{audio_path}`\n"
                f"🧾 Manifest: `{os.path.join(meeting['meeting_dir'], 'manifest.json')}`"
            )
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
        duration = str(utc_now_dt() - meeting["start_time"]).split(".")[0]

        embed = discord.Embed(title="🎙️ Active Meeting", color=0x00FF00)
        embed.add_field(name="Status",     value="🟢 **RECORDING**",            inline=True)
        embed.add_field(name="Duration",   value=f"⏱️ {duration}",              inline=True)
        embed.add_field(name="Started by", value=f"<@{meeting['started_by']}>", inline=True)

        audio_path = meeting.get("raw_audio_path") or "pending…"
        embed.add_field(name="Audio file", value=f"`{audio_path}`", inline=False)
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
        
        start_time = data["start_time"]
        if isinstance(start_time, dt.datetime) and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=dt.timezone.utc)

        age = (utc_now_dt() - start_time).total_seconds()
        if age > 86400:
            await ctx.send("❌ Saved meeting has expired (older than 24 hours).")
            return

        raw_audio_path = data.get("raw_audio_path") or data.get("mix_audio_path")

        active_meetings[guild_id] = {
            "channel":        ctx.channel,
            "channel_id":     ctx.channel.id,
            "vc":             None,
            "sink":           None,
            "start_time":     start_time,          # ✅ normalizado
            "started_by":     data["started_by"],
            "meeting_id":     data.get("meeting_id"),
            "meeting_dir":    data.get("meeting_dir"),
            "raw_audio_path": raw_audio_path,      # ✅ só raw
        }

        audio_path = raw_audio_path or "unknown"
        await ctx.send(
            f"✅ Meeting metadata restored.\n"
            f"🎙️ Audio file: `{audio_path}`\n"
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
