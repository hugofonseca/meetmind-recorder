import datetime
import re
from pathlib import Path

import requests


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


def process_meeting_in_minutes_api(
    guild_id: int,
    meeting: dict,
    audio_path: str,
    *,
    base_url: str,
    timeout: int,
    logger=None,
) -> dict:
    meeting_id = build_meeting_id(guild_id, meeting)

    payload = {
        "meeting_id": meeting_id,
        "audio_path": str(Path(audio_path).resolve()),
    }

    if logger:
        logger.info(f"[minutes_api] Sending payload: {payload}")

    endpoint = f"{base_url.rstrip('/')}/process-meeting"

    response = requests.post(
        endpoint,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()