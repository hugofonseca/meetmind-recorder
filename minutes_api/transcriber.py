import json
import math
import shutil
import subprocess
from pathlib import Path
from groq import Groq

MODEL = "whisper-large-v3"
LANGUAGE = "pt"
TEMPERATURE = 0.0

CHUNK_LEN = 600
OVERLAP = 5
STEP = CHUNK_LEN - OVERLAP
KEEP_CHUNKS = False
EPS_DEDUPE = 0.10


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"{name} não encontrado no PATH. Instale o FFmpeg e reabra o terminal."
        )


def ffprobe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)


def make_chunks_flac_16k_mono(
    input_audio: Path, outdir: Path, chunk_len: int, overlap: int
) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    step = chunk_len - overlap
    duration = ffprobe_duration_seconds(input_audio)
    n = math.ceil(max(duration - overlap, 0.01) / step)

    chunks = []
    for i in range(n):
        start = i * step
        outfile = outdir / f"{input_audio.stem}_chunk_{i:03d}.flac"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(chunk_len),
            "-i",
            str(input_audio),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-map",
            "0:a",
            "-c:a",
            "flac",
            str(outfile),
        ]
        subprocess.run(cmd, check=True)
        chunks.append(outfile)

    return chunks


def dedupe_by_timeline(segments: list[dict], eps: float = 0.10) -> list[dict]:
    out = []
    last_end = 0.0

    for seg in segments:
        end = float(seg["end"])
        if end > last_end + eps:
            out.append(seg)
            last_end = max(last_end, end)

    return out


def transcribe_ogg_file(
    audio_path: str,
    groq_api_key: str,
    chunks_dir: str = "data/chunks",
    transcripts_dir: str = "data/transcripts",
) -> dict:
    require_tool("ffmpeg")
    require_tool("ffprobe")

    audio = Path(audio_path)
    if not audio.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {audio}")

    if audio.suffix.lower() != ".ogg":
        raise ValueError("O pipeline final espera arquivo .ogg")

    chunks_dir = Path(chunks_dir)
    transcripts_dir = Path(transcripts_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    client = Groq(api_key=groq_api_key)

    chunk_folder = chunks_dir / audio.stem
    chunks = make_chunks_flac_16k_mono(audio, chunk_folder, CHUNK_LEN, OVERLAP)

    all_segments = []
    fulltext_parts = []

    for i, chunk_path in enumerate(chunks):
        chunk_start = i * STEP

        with open(chunk_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                file=f,
                model=MODEL,
                language=LANGUAGE,
                temperature=TEMPERATURE,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        data = resp.to_dict()
        segments = data.get("segments") or []

        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            start = float(seg.get("start", 0.0)) + chunk_start
            end = float(seg.get("end", 0.0)) + chunk_start

            all_segments.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                }
            )

        chunk_text = (data.get("text") or "").strip()
        if chunk_text:
            fulltext_parts.append(chunk_text)

    all_segments = dedupe_by_timeline(all_segments, eps=EPS_DEDUPE)

    base = audio.stem
    out_json = transcripts_dir / f"{base}.transcript.json"
    out_txt = transcripts_dir / f"{base}.txt"

    out_json.write_text(
        json.dumps(
            {
                "audio_file": str(audio),
                "text": "\n".join(fulltext_parts),
                "segments": all_segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    out_txt.write_text(
        "\n".join(seg["text"] for seg in all_segments),
        encoding="utf-8",
    )

    if not KEEP_CHUNKS and chunk_folder.exists():
        shutil.rmtree(chunk_folder, ignore_errors=True)

    return {
        "audio_file": str(audio),
        "transcript_json": str(out_json),
        "transcript_txt": str(out_txt),
        "text": out_txt.read_text(encoding="utf-8"),
    }