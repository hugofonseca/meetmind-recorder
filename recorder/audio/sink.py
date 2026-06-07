##import tempfile
##import os
import wave
import logging
from discord.ext import voice_recv
from utils.paths import build_temp_wav_path, build_final_ogg_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audio sink — captures PCM and writes a stereo 48 kHz WAV file
# ---------------------------------------------------------------------------
class AudioSink(voice_recv.AudioSink):
    """Writes every incoming voice packet to a single mixed WAV file."""

    def __init__(self, meeting: dict):
        super().__init__()
        self.stopped = False
        self.meeting = meeting

        self.pcm_bytes_written = 0
        self.write_calls = 0
        self.first_audio_logged = False

        self.mix_path = build_temp_wav_path(meeting["start_time"])
        self.final_ogg_path = build_final_ogg_path(meeting["start_time"])

        self.mix_wav = wave.open(self.mix_path, "wb")
        self.mix_wav.setnchannels(2)
        self.mix_wav.setsampwidth(2)
        self.mix_wav.setframerate(48000)

        # Compatibilidade: manter a chave antiga por enquanto
        meeting["mix_audio_path"] = self.mix_path

        # Caminhos mais explícitos
        meeting["raw_audio_path"] = self.mix_path
        meeting["final_ogg_path"] = self.final_ogg_path

        logger.info(f"[AudioSink] Recording started (temp WAV): {self.mix_path}")
        logger.info(f"[AudioSink] Final OGG target: {self.final_ogg_path}")
        logger.info("[AudioSink] DEBUG VERSION COM CONTADORES ATIVA")

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        if self.stopped:
            return

        if not data or not data.pcm:
            return

        try:
            self.write_calls += 1
            self.pcm_bytes_written += len(data.pcm)

            if not self.first_audio_logged:
                logger.info(
                    f"[AudioSink] First PCM packet received: user={user} bytes={len(data.pcm)}"
                )
                self.first_audio_logged = True

            self.mix_wav.writeframes(data.pcm)

        except Exception as e:
            logger.error(f"[AudioSink] Write error: {e}")

    def cleanup(self) -> None:
        if self.stopped:
            return

        self.stopped = True
        try:
            if getattr(self, "mix_wav", None):
                self.mix_wav.close()
                self.mix_wav = None

            logger.info(
                f"[AudioSink] Temp WAV closed: {self.mix_path} | "
                f"write_calls={self.write_calls} | "
                f"pcm_bytes_written={self.pcm_bytes_written}"
            )

        except Exception as e:
            logger.error(f"[AudioSink] Cleanup error: {e}")