import logging
import os
import discord
import ffmpeg
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

def ffprobe_duration_seconds(path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)

def validate_audio_file(path: str, min_size_bytes: int | None = None) -> float:
    """
    Valida se o arquivo existe, tem tamanho mínimo e pode ser lido pelo ffprobe.
    Retorna a duração em segundos se estiver ok.
    """
    p = Path(path)

    # define tamanho mínimo automaticamente conforme extensão
    if min_size_bytes is None:
        ext = p.suffix.lower()
        if ext == ".ogg":
            min_size_bytes = 4096
        elif ext == ".wav":
            min_size_bytes = 1024
        else:
            min_size_bytes = 1024

    if not p.exists():
        raise RuntimeError(f"Arquivo não encontrado: {path}")

    size = p.stat().st_size
    if size < min_size_bytes:
        raise RuntimeError(f"Arquivo muito pequeno ou truncado: {path} ({size} bytes)")

    try:
        duration = ffprobe_duration_seconds(path)
        return duration
    except Exception as e:
        raise RuntimeError(f"Arquivo inválido para ffprobe: {path} ({e})")

# ---------------------------------------------------------------------------
# Compress WAV → OGG and upload to Discord ?????????
# ---------------------------------------------------------------------------
async def compress_and_upload(
    channel: discord.TextChannel,
    wav_path: str,
    duration: str,
) -> str | None:
    """
    Convert WAV to OGG Opus and send as a Discord attachment.

    Returns:
        - ogg_path (str) se o OGG foi gerado e validado com sucesso
        - None se a conversão/validação falhar

    O upload para o Discord ainda ocorre:
        - com OGG se válido
        - com WAV como fallback se o OGG falhar
    """
    os.makedirs("meeting_audio", exist_ok=True)

    base_name = os.path.splitext(os.path.basename(wav_path))[0]
    ogg_path = os.path.join("meeting_audio", f"{base_name}.ogg")

    upload_path = wav_path
    process_path = None  # só será preenchido se o OGG passar na validação
    ogg_created = False

    try:
        # 1) valida o WAV antes da conversão
        wav_duration = validate_audio_file(wav_path)
        logger.info(f"[compress_and_upload] WAV validated: {wav_path} ({wav_duration:.2f}s)")

        # 2) converte WAV -> OGG
        out, err = (
            ffmpeg
            .input(wav_path)
            .output(ogg_path, acodec="libopus", ab="64k", ar=48000)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )

        # 3) valida o OGG depois da conversão
        ogg_duration = validate_audio_file(ogg_path)
        logger.info(f"[compress_and_upload] OGG created and validated: {ogg_path} ({ogg_duration:.2f}s)")

        upload_path = ogg_path
        process_path = ogg_path
        ogg_created = True

    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else "sem stderr"
        logger.warning(f"[compress_and_upload] ffmpeg failed, falling back to WAV: {stderr}")

    except Exception as e:
        logger.warning(f"[compress_and_upload] OGG invalid, falling back to WAV: {e}")

    # Upload para o Discord (OGG válido ou WAV fallback)
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
        if e.status == 413:
            await channel.send(
                f"✅ Meeting ended (duration: {duration}).\n"
                f"⚠️ Audio file too large to upload to Discord.\n"
                f"📁 Saved locally at: `{upload_path}`"
            )
            logger.warning(f"[compress_and_upload] File too large for Discord: {upload_path}")
        else:
            logger.error(f"[compress_and_upload] HTTP error uploading file: {e}")
            raise

    # Remove o WAV temporário somente se o OGG foi gerado com sucesso
    if ogg_created and os.path.exists(wav_path):
        try:
            os.remove(wav_path)
            logger.info(f"[compress_and_upload] Temp WAV removed: {wav_path}")
        except Exception as e:
            logger.warning(f"[compress_and_upload] Could not remove temp WAV: {wav_path} ({e})")

    return process_path