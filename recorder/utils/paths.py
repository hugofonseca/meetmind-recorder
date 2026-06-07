import os
import tempfile
from datetime import datetime


def build_recording_basename(start_time: datetime) -> str:
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    return f"meeting_{timestamp}"


def ensure_meeting_audio_dir() -> str:
    audio_dir = "meeting_audio"
    os.makedirs(audio_dir, exist_ok=True)
    return audio_dir


def ensure_temp_audio_dir() -> str:
    temp_dir = os.path.join(tempfile.gettempdir(), "meetmind-recorder")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir


def build_temp_wav_path(start_time: datetime) -> str:
    temp_dir = ensure_temp_audio_dir()
    base_name = build_recording_basename(start_time)
    return os.path.join(temp_dir, f"{base_name}.wav")


def build_final_ogg_path(start_time: datetime) -> str:
    audio_dir = ensure_meeting_audio_dir()
    base_name = build_recording_basename(start_time)
    return os.path.join(audio_dir, f"{base_name}.ogg")