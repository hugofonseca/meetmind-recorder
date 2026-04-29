# meetmind-recorder (Windows)

Bot de gravação e transcrição para reuniões no Discord (Windows) com:
- Transcrição em tempo real
- Gravação local de áudio (WAV)
- Geração de transcript (PDF/DOCX/TXT)
- Fallback automático: se a captura falhar em canal de voz normal, orienta usar Stage

> ✅ Suporte inicial: **Windows 10/11**  
> 🎙️ Recomendação operacional: use **Stage Channel** para captura estável.

---

## ✅ Requisitos (Windows)
- Windows 10/11
- Python 3.11.9
- Token de bot do Discord (`DISCORD_TOKEN`)

---

## 🚀 Setup rápido (PowerShell)

### 1) Clonar o repositório
'''
git clone https://github.com/hugofonseca/meetmind-recorder.git
cd meetmind-recorder
'''
### 2) Criar e ativar ambiente virtual
'''
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1
'''
- após o comando acima, o terminal deverá acusar que o venv está ativdado

### 3) Instalar dependências (dentro do venv)
'''
python -m pip install --upgrade pip
pip install -r requirements.lock.txt
'''
### 4) Informar DISCORD_TOKEN
- Copiar token no site do discord e colar dentro do arquivo
.env.example

### 5) Rodar o bot
'''
python -u main.py

---

## 🎙️ Como usar (recomendado)

### 1) Crie/Use um Stage Channel no servidor:

- Nome sugerido: 📌 Meeting Room (Transcrição)

- Entre no chat de texto do Stage e rode:
'''
!start_meeting portuguese

- Fale normalmente e, para finalizar, rode:
'''
!end_meeting

✅ O bot cria um arquive .wav da gravação da reunião dentro da subpasta meeting_audio. Além disso, no servidor do Discord, ele cria um canal de texto meeting-transcription-..., publica transcrições simultâneas. Quando finalizar a reunião, o bot envia o arquivo final da transcrição para download no canal meeting-transcription criado.

### 2) 🧩 Comandos

| Command | Description | Usage Example |
|---------|-------------|---------------|
| `!start_meeting [language]` | Start a new meeting with transcription | `!start_meeting english`<br>`!start_meeting arabic`<br>`!start_meeting auto` |
| `!end_meeting [format]` | End meeting and generate transcript | `!end_meeting pdf`<br>`!end_meeting docx` |
| `!ask <question>` | Ask AI about meeting content | `!ask What did John say about the budget?` |
| `!meeting_status` | Check current meeting status | `!meeting_status` |
| `!languages` | Show supported languages | `!languages` |
| `!meeting_help` | Display help information | `!meeting_help` |

### 3) 📌 Observações importantes

- O bot foi otimizado para funcionar com Stage Channel.
- Em canais de voz normais, a captura pode ser instável; o bot possui fallback automático orientando o Stage.

### 4) 📁 Saídas geradas localmente

- meeting_audio/ → gravações WAV locais
- transcript_*.pdf|docx|txt → arquivos de transcript gerados

Essas pastas/arquivos são ignorados pelo .gitignore.

### 5) 🧯 Troubleshooting
Veja, dentro da subpasta docs, os arquivos:
- windows-setup.md
- troubleshooting.md

### 6) 📜 Licença & créditos
- Projeto empacotado/documentado para execução local no Windows. 
- Inclui melhorias operacionais (Stage recomendado, fallback e gravação local).