# meetmind-recorder (Windows)

Bot de transcrição para reuniões no Discord (Windows) com:
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
git clone https://github.com/hugofonseca/meetmind-recorder.git
cd meetmind-recorder

### 2) Criar e ativar ambiente virtual
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1
'''após o comando acima, o terminal deverá acusar que o venv está ativdado'''

### 3) Instalar dependências (dentro do venv)
python -m pip install --upgrade pip
pip install -r requirements.lock.txt

### 4) Informar DISCORD_TOKEN
Copiar token no site do discord e colar dentro do arquivo
.env.example

### 5) Rodar o bot
python -u main.py

---

🎙️ Como usar (recomendado)

Crie/Use um Stage Channel no servidor:

Nome sugerido: 📌 Meeting Room (Transcrição)


Entre no Stage
Rode: !start_meeting portuguese
Fale normalmente
Finalize: !end_meeting

✅ O bot cria um arquive .wav da gravação da reunião dentro da subpasta meeting_audio. Além disso, no servidor do Discord, ele cria um canal de texto meeting-transcription-..., publica transcrições simultâneas. Ao finalizar a reunião, o bot envia o arquivo final da transcrição nesse novo canal.

🧩 Comandos principais

!start_meeting [language] — inicia a reunião/transcrição
!end_meeting [pdf|docx|txt] — encerra e gera o transcript
!meeting_status — status da reunião
!meeting_help — ajuda

📌 Observações importantes

O bot foi otimizado para funcionar com Stage Channel.
Em canais de voz normais, a captura pode ser instável; o bot possui fallback automático orientando o Stage.

📁 Saídas geradas localmente

meeting_audio/ → gravações WAV locais
transcript_*.pdf|docx|txt → arquivos de transcript gerados

Essas pastas/arquivos são ignorados pelo .gitignore.

🧯 Troubleshooting
Veja:
docs/windows-setup.md
docs/troubleshooting.md

📜 Licença & créditos
Projeto empacotado/documentado para execução local no Windows. 
Inclui melhorias operacionais (Stage recomendado, fallback e gravação local).