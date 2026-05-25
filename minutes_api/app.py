import os
import json
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from transcriber import transcribe_ogg_file
from pipeline import processar_transcricao

load_dotenv()

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", "5000"))

BASE_DIR = Path(__file__).resolve().parent
TRANSCRIPTS_DIR = BASE_DIR / "data" / "transcripts"
MINUTES_DIR = BASE_DIR / "data" / "minutes"
CHUNKS_DIR = BASE_DIR / "data" / "chunks"

TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
MINUTES_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/gerar-ata", methods=["POST"])
def gerar_ata():
    data = request.get_json(silent=True) or {}
    transcript = data.get("transcript")

    if not transcript:
        transcript = request.form.get("transcript", "")

    if not transcript or not transcript.strip():
        return jsonify({"erro": "Transcrição vazia"}), 400

    result = processar_transcricao(
        transcricao=transcript,
        groq_api_key=GROQ_API_KEY,
        meeting_id="manual_input",
        minutes_dir=str(MINUTES_DIR)
    )

    return jsonify(result)


@app.post("/process-meeting")
def process_meeting():
    data = request.get_json(force=True)

    meeting_id = (data.get("meeting_id") or "").strip()
    audio_path = (data.get("audio_path") or "").strip()

    if not meeting_id or not audio_path:
        return jsonify({"erro": "meeting_id e audio_path são obrigatórios"}), 400

    transcription = transcribe_ogg_file(
        audio_path=audio_path,
        groq_api_key=GROQ_API_KEY,
        chunks_dir=str(CHUNKS_DIR),
        transcripts_dir=str(TRANSCRIPTS_DIR)
    )

    result = processar_transcricao(
        transcricao=transcription["text"],
        groq_api_key=GROQ_API_KEY,
        meeting_id=meeting_id,
        minutes_dir=str(MINUTES_DIR)
    )

    result["audio_file"] = audio_path
    result["transcript_txt"] = transcription["transcript_txt"]
    result["transcript_json"] = transcription["transcript_json"]

    out_file = MINUTES_DIR / f"{meeting_id}.minutes.json"
    out_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return jsonify(result)


@app.get("/meetings")
def list_meetings():
    files = sorted(MINUTES_DIR.glob("*.minutes.json"), reverse=True)
    items = []

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        items.append({
            "id": data.get("id"),
            "tipo": data.get("tipo"),
            "preview": (data.get("ata") or "")[:180]
        })

    return jsonify(items)


@app.get("/meetings/<meeting_id>")
def get_meeting(meeting_id: str):
    file = MINUTES_DIR / f"{meeting_id}.minutes.json"

    if not file.exists():
        return jsonify({"erro": "Ata não encontrada"}), 404

    return jsonify(json.loads(file.read_text(encoding="utf-8")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)