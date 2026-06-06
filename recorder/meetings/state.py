from typing import Any

active_meetings: dict[int, dict[str, Any]] = {}


def get_active_meeting(guild_id: int) -> dict[str, Any] | None:
    return active_meetings.get(guild_id)


def set_active_meeting(guild_id: int, meeting: dict[str, Any]) -> None:
    active_meetings[guild_id] = meeting


def clear_active_meeting(guild_id: int) -> None:
    active_meetings.pop(guild_id, None)


def has_active_meeting(guild_id: int) -> bool:
    return guild_id in active_meetings


def iter_active_meetings():
    return active_meetings.items()


def clear_all_active_meetings() -> None:
    active_meetings.clear()