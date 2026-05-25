import json
import time
from pathlib import Path
from groq import Groq

LINHAS_POR_CHUNK = 300
MODELO_LEVE = "llama-3.1-8b-instant"
MODELO_ROBUSTO = "llama-3.3-70b-versatile"


def dividir_em_chunks(texto: str, linhas_por_chunk: int) -> list[str]:
    linhas = texto.splitlines()
    chunks = []

    for i in range(0, len(linhas), linhas_por_chunk):
        chunk = "\n".join(linhas[i:i + linhas_por_chunk])
        if chunk.strip():
            chunks.append(chunk)

    return chunks


def resumir_chunk(client: Groq, chunk: str, indice: int, total: int) -> str:
    resposta = client.chat.completions.create(
        model=MODELO_LEVE,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você resume trechos de transcrições de reunião. "
                    "Extraia participantes mencionados, decisões, tarefas, prazos e tópicos discutidos. "
                    "Seja objetivo e preserve as informações importantes."
                ),
            },
            {
                "role": "user",
                "content": f"Resuma este trecho da reunião ({indice + 1}/{total}):\n\n{chunk}",
            },
        ],
    )
    time.sleep(2)
    return (resposta.choices[0].message.content or "").strip()


def classificar_reuniao(client: Groq, transcricao: str) -> str:
    resposta = client.chat.completions.create(
        model=MODELO_LEVE,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você classifica reuniões. "
                    "Responda apenas com uma palavra entre: "
                    "daily, brainstorming, planejamento, status, retrospectiva, decisao."
                ),
            },
            {
                "role": "user",
                "content": f"Classifique esta reunião:\n\n{transcricao[:6000]}",
            },
        ],
    )
    return (resposta.choices[0].message.content or "").strip().lower()


def gerar_ata(client: Groq, resumo_consolidado: str, tipo: str) -> str:
    instrucoes = {
        "daily": "Para cada participante, liste o que fez, o que vai fazer e impedimentos.",
        "brainstorming": "Liste as ideias geradas, agrupadas por tema.",
        "planejamento": "Extraia decisões tomadas, tarefas com responsável e prazos.",
        "status": "Estruture por andamento, riscos, bloqueios, próximos passos e responsáveis.",
        "retrospectiva": "Destaque pontos positivos, problemas, aprendizados e ações de melhoria.",
        "decisao": "Liste claramente as alternativas discutidas, decisão final, justificativa e próximos passos.",
    }

    instrucao = instrucoes.get(
        tipo, "Gere uma ata com decisões, tarefas, responsáveis e prazos."
    )

    resposta = client.chat.completions.create(
        model=MODELO_ROBUSTO,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente especialista em gerar atas de reunião. "
                    f"{instrucao} "
                    "Use linguagem formal, organize em seções com títulos em português e gere Markdown limpo."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Com base nos resumos abaixo, gere uma ata estruturada e completa:\n\n"
                    f"{resumo_consolidado}"
                ),
            },
        ],
    )
    return (resposta.choices[0].message.content or "").strip()


def processar_transcricao(
    transcricao: str,
    groq_api_key: str,
    meeting_id: str,
    minutes_dir: str = "data/minutes",
) -> dict:
    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY não informada")

    transcricao = (transcricao or "").strip()
    if not transcricao:
        raise ValueError("Transcrição vazia")

    client = Groq(api_key=groq_api_key)

    minutes_path = Path(minutes_dir)
    minutes_path.mkdir(parents=True, exist_ok=True)

    chunks = dividir_em_chunks(transcricao, LINHAS_POR_CHUNK)

    if len(chunks) == 1:
        resumo_consolidado = transcricao
    else:
        resumos = [
            resumir_chunk(client, chunk, i, len(chunks))
            for i, chunk in enumerate(chunks)
        ]
        resumo_consolidado = "\n\n---\n\n".join(
            [f"PARTE {i + 1}\n{resumo}" for i, resumo in enumerate(resumos)]
        )

    tipo = classificar_reuniao(client, resumo_consolidado[:3000]).upper()
    ata = gerar_ata(client, resumo_consolidado, tipo.lower())

    resultado = {
        "id": meeting_id,
        "tipo": tipo,
        "ata": ata,
        "resumo_consolidado": resumo_consolidado,
    }

    out_file = minutes_path / f"{meeting_id}.minutes.json"
    out_file.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return resultado