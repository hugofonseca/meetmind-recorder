import logging
import os
import pickle

from meetings.state import (
    iter_active_meetings,
    set_active_meeting,
    clear_all_active_meetings,
)

logger = logging.getLogger(__name__)


def save_meetings(meetings_file_path: str) -> None:
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
        with open(meetings_file_path, "wb") as f:
            pickle.dump(serialisable, f)
    except Exception as e:
        logger.error(f"[save_meetings] Failed: {e}")


def load_meetings(meetings_file_path: str) -> None:
    """Load persisted meeting metadata on startup."""
    if not os.path.exists(meetings_file_path):
        return

    try:
        with open(meetings_file_path, "rb") as f:
            saved: dict = pickle.load(f)

        # Evita duplicar/mesclar dados se essa função for chamada mais de uma vez
        clear_all_active_meetings()

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
