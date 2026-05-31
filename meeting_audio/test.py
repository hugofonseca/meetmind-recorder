import os
import json
import math
import shutil
import subprocess
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq


# =========================
# CONFIGURAÇÃO
# =========================
MODEL = "whisper-large-v3"  # alta precisão [1](https://www.youtube.com/watch?v=6sim9aF3g2c)
LANGUAGE = "pt"
TEMPERATURE = 0.0

# Chunking
CHUNK_LEN = 600   # 10 minutos
OVERLAP = 5       # 5 segundos
STEP = CHUNK_LEN - OVERLAP

# Saídas
KEEP_CHUNKS = True          # mude para False se quiser apagar chunks no final
EPS_DEDUPE = 0.10           # tolerância (segundos) para remover duplicatas de overlap


# =========================
# CAMINHOS
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent                  # ...\meeting_audio
PROJECT_DIR = SCRIPT_DIR.parent                               # ...\meetmind-recorder
DOTENV_PATH = PROJECT_DIR / ".env"                            # ...\meetmind-recorder\.env
AUDIO_PATH = SCRIPT_DIR / "audio.m4a"                         # ...\meeting_audio\audio.m4a
CHUNKS_DIR = SCRIPT_DIR / "chunks"                            # ...\meeting_audio\chunks

#OUT_JSON = SCRIPT_DIR / "transcricao_timestamps.json"
#OUT_TXT = SCRIPT_DIR / "transcricao.txt"


# =========================
# FUNÇÕES AUXILIARES
# =========================
def require_tool(name: str):
    """Garante que ffmpeg/ffprobe existem no PATH."""
    if shutil.which(name) is None:
        raise RuntimeError(
            f"'{name}' não encontrado no PATH. "
            f"Instale o FFmpeg e reabra o terminal."
        )

def choose_audio_interactively(folder: Path) -> Path:
    """
    Lista apenas arquivos .ogg na pasta informada,
    mostra duração de todos e permite escolher pelo número.
    """

    # Filtra somente .ogg na pasta (sem subpastas)
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".ogg"]

    if not files:
        raise FileNotFoundError(
            f"Nenhum arquivo .ogg encontrado em {folder}"
        )

    # Ordena por mais recente primeiro
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    print("\n📂 Áudios .ogg encontrados em:", folder)
    print("Digite o número para escolher ou 0 para sair.\n")

    # Buscar duração de todos os arquivos
    durations = []
    for f in files:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(f)
            ]
            out = subprocess.check_output(cmd, text=True).strip()
            seconds = float(out)

            m, s = divmod(int(seconds), 60)
            h, m = divmod(m, 60)

            if h > 0:
                dur_txt = f"{h}h {m:02d}m {s:02d}s"
            else:
                dur_txt = f"{m}m {s:02d}s"

        except Exception:
            dur_txt = "duração desconhecida"

        durations.append(dur_txt)

    # Exibir lista
    for i, (f, dur) in enumerate(zip(files, durations), start=1):
        print(f"{i:2d}) {f.name}  |  {dur}")

    # Loop de escolha
    while True:
        choice = input("\nEscolha (0 para sair): ").strip()

        if choice == "0":
            print("👋 Encerrando programa...")
            raise SystemExit()

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(files):
                selected = files[index - 1]
                print(f"\n✅ Selecionado: {selected.name}\n")
                return selected

        print("❌ Opção inválida. Tente novamente.")


def ffprobe_duration_seconds(path: Path) -> float:
    """Retorna duração do áudio em segundos usando ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)

def make_chunks_flac_16k_mono(input_audio: Path, out_dir: Path, chunk_len: int, overlap: int) -> list[Path]:
    """
    Gera chunks sobrepostos em FLAC 16kHz mono:
    - FLAC é eficiente (lossless) para reduzir tamanho [1](https://www.youtube.com/watch?v=6sim9aF3g2c)
    - 16k mono é ideal para ASR [1](https://www.youtube.com/watch?v=6sim9aF3g2c)
    """
    out_dir.mkdir(exist_ok=True)
    step = chunk_len - overlap

    duration = ffprobe_duration_seconds(input_audio)
    n = math.ceil((duration - overlap) / step)

    chunks = []
    for i in range(n):
        start = i * step
        out_file = out_dir / f"chunk_{i:03d}.flac"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(chunk_len),
            "-i", str(input_audio),
            "-ac", "1",
            "-ar", "16000",
            "-map", "0:a",
            "-c:a", "flac",
            str(out_file)
        ]
        subprocess.run(cmd, check=True)
        chunks.append(out_file)

    return chunks

def txt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def dedupe_by_timeline(segments: list[dict], eps: float = 0.10) -> list[dict]:
    """
    Remove duplicatas do overlap mantendo apenas segmentos que avançam a linha do tempo.
    Funciona bem quando há overlap pequeno (5s) e timestamps coerentes.
    """
    out = []
    last_end = 0.0
    for seg in segments:
        end = float(seg["end"])
        if end > last_end + eps:
            out.append(seg)
            last_end = max(last_end, end)
    return out

def sanitize_filename(text: str) -> str:
    """
    Normaliza o nome do arquivo para Windows:
    - troca espaços por underscore
    - remove caracteres inválidos: \ / : * ? " < > |
    - reduz múltiplos underscores
    """
    text = text.strip().replace(" ", "_")
    text = re.sub(r'[\\/:*?"<>|]+', "", text)
    text = re.sub(r"_+", "_", text)
    return text


def unique_path_by_counter(path: Path) -> Path:
    """
    Se o arquivo já existir, cria um novo com sufixo incremental:
    nome.ext -> nome_001.ext -> nome_002.ext -> ...

    Retorna um Path que não existe ainda.
    """
    if not path.exists():
        return path

    parent = path.parent
    stem = path.stem
    suffix = path.suffix

    i = 1
    while True:
        candidate = parent / f"{stem}_{i:03d}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1

# =========================
# MAIN
# =========================
def main():   
    # 1) Checagens básicas (ferramentas primeiro)
    require_tool("ffmpeg")
    require_tool("ffprobe")
    # 1.1) Selecionar o áudio .ogg na pasta meeting_audio
    selected_audio = choose_audio_interactively(SCRIPT_DIR)
    # (opcional) garantir que existe
    if not selected_audio.exists():
        raise FileNotFoundError(f"Áudio não encontrado em: {selected_audio}")

    # 2) Carregar .env (na pasta do projeto)
    load_dotenv(dotenv_path=DOTENV_PATH)
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(f"GROQ_API_KEY não encontrada. Verifique: {DOTENV_PATH}")

    # 3) Criar cliente Groq (chave via env/dotenv é o padrão recomendado) [2](https://www.reddit.com/r/ffmpeg/comments/16cok9s/gyanffmpeg_adds_a_worthless_folder_to_the_path/)[3](https://www.techbloat.com/how-to-add-ffmpeg-to-path-windows.html)
    client = Groq(api_key=api_key)

    # 4) Gerar chunks com overlap
    print("⏳ Gerando chunks (FLAC 16k mono) com overlap...")
    chunks = make_chunks_flac_16k_mono(selected_audio, CHUNKS_DIR, CHUNK_LEN, OVERLAP)
    print(f"✅ {len(chunks)} chunks gerados em: {CHUNKS_DIR}")

    # 5) Transcrever chunks com timestamps por segmento
    # Para timestamps: response_format="verbose_json" e timestamp_granularities=["segment"] [1](https://www.youtube.com/watch?v=6sim9aF3g2c)
    all_segments = []
    full_text_parts = []

    for i, chunk_path in enumerate(chunks):
        chunk_start = i * STEP  # importante: usa STEP (chunk_len - overlap)

        print(f"🎙️ Transcrevendo {chunk_path.name} ({i+1}/{len(chunks)})...")

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

        # Texto bruto do chunk (opcional para auditoria)
        chunk_text = (data.get("text") or "").strip()
        if chunk_text:
            full_text_parts.append(chunk_text)

        # Segmentos com start/end (segundos) — ajusta para timeline global
        segments = data.get("segments") or []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            start = float(seg.get("start", 0.0)) + chunk_start
            end = float(seg.get("end", 0.0)) + chunk_start

            all_segments.append({
                "start": start,
                "end": end,
                "text": text
            })

    # 6) Deduplicar overlap (por avanço de timeline)
    all_segments = dedupe_by_timeline(all_segments, eps=EPS_DEDUPE)

    # 7) Exportar JSON e TXT sem sobrescrever (baseado no nome do áudio)
    audio_base = sanitize_filename(selected_audio.stem)  # nome do .m4a sem extensão

    out_json = unique_path_by_counter(SCRIPT_DIR / f"{audio_base}.json")
    out_txt  = unique_path_by_counter(SCRIPT_DIR / f"{audio_base}.txt")

    # JSON
    out_json.write_text(
        json.dumps(
            {"text": "\n".join(full_text_parts), "segments": all_segments},
            ensure_ascii=False, indent=2
        ),
        encoding="utf-8"
    )

    # TXT (1 linha por segmento)
    txt_lines = [seg["text"] for seg in all_segments]
    out_txt.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")

    print("\n✅ Concluído!")
    print(f"📄 JSON: {out_json}")
    print(f"📝 TXT : {out_txt}")

    # 9) Opcional: limpar chunks
    if not KEEP_CHUNKS and CHUNKS_DIR.exists():
        shutil.rmtree(CHUNKS_DIR, ignore_errors=True)
        print("🧹 Chunks removidos.")

if __name__ == "__main__":
    main()