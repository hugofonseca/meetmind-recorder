MeetMind
========

Visão geral
-----------
MeetMind é um agente integrado para:
- gravar reuniões no Discord;
- transcrever áudio e gerar atas automaticamente;
- visualizar e interagir com resultados em um dashboard Flutter.

O agente é composto por três módulos principais:
- recorder/: bot do Discord responsável por entrar no canal, gravar a reunião e enviar o áudio para processamento.
- minutes_api/: API Flask responsável por transcrever o áudio e gerar a ata/minutes.
- dashboard_flutter/: interface Flutter para visualização e interação com os resultados.

Arquitetura atual
-----------------
Estrutura principal:

meetmind-recorder/
- recorder/
- minutes_api/
- dashboard_flutter/

Estrutura atual do recorder/:

recorder/
- main.py
- audio/
  - sink.py
  - processing.py
- meetings/
  - state.py
  - service.py
  - persistence.py
- integrations/
  - minutes_api.py
- utils/
  - paths.py

Responsabilidades no recorder/:
- main.py: entrypoint do bot, configuração e registro de comandos/eventos.
- audio/sink.py: captura e gravação do áudio da reunião.
- audio/processing.py: validação, conversão e upload do áudio final.
- meetings/state.py: estado em memória das reuniões ativas.
- meetings/service.py: fluxo principal de reuniões (start, end, status, auto-end e falhas).
- meetings/persistence.py: persistência e restauração do estado das reuniões.
- integrations/minutes_api.py: integração com a API Flask de atas.
- utils/paths.py: centralização dos caminhos e nomes de arquivos.

Artefatos gerados
-----------------
Backend (minutes_api):
- minutes_api/data/transcripts/
- minutes_api/data/chunks/
- minutes_api/data/minutes/

Recorder:
- recorder/meeting_audio/

Observação sobre áudio:
- o recorder grava inicialmente um WAV temporário;
- o WAV é convertido para OGG, que é o formato final do pipeline;
- o WAV temporário é removido após a conversão bem-sucedida.

Principais avanços recentes
---------------------------
- O recorder foi modularizado e deixou de concentrar toda a lógica em um main.py extenso.
- O pipeline de áudio foi consolidado com WAV temporário + OGG final.
- A persistência do estado das reuniões foi separada da lógica de negócio.
- A integração com a API de atas foi isolada em módulo próprio.
- Caminhos e nomes de arquivos passaram a ser centralizados em utilitário específico.
- O projeto ficou mais legível, testável e sustentável.

Pré-requisitos mínimos
----------------------
Para os módulos Python (minutes_api e recorder):
- Python 3.10 ou superior.
- FFmpeg completo instalado e disponível no PATH do sistema.
- Importante: o projeto precisa dos executáveis "ffmpeg" e "ffprobe" acessíveis no PATH.
- Uma chave GROQ_API_KEY.
- Um token de bot do Discord.

Para o dashboard Flutter (dashboard_flutter):
- Flutter SDK instalado e acessível no PATH do sistema.
- Google Chrome ou Microsoft Edge instalado.

Ambientes virtuais
------------------
Cada módulo Python usa seu próprio ambiente virtual:
- minutes_api/.venv
- recorder/.venv

O dashboard_flutter não usa venv de Python; ele depende do Flutter SDK instalado no sistema.

Variáveis de ambiente
---------------------
minutes_api/.env
GROQ_API_KEY=sua_chave_aqui
PORT=5000

recorder/.env
DISCORD_TOKEN=seu_token_aqui
MINUTES_API_URL=http://127.0.0.1:5000

Instalação
----------
1) API de atas (minutes_api)
cd minutes_api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

2) Bot recorder (recorder)
cd recorder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

3) Dashboard Flutter (dashboard_flutter)
cd dashboard_flutter
flutter --version
flutter doctor
flutter devices
flutter pub get

Como executar localmente
------------------------
1) Subir a API Flask
cd minutes_api
.\.venv\Scripts\Activate.ps1
python app.py

Validação:
http://127.0.0.1:5000/health
Resposta esperada:
{"status": "ok"}

2) Subir o bot recorder
cd recorder
.\.venv\Scripts\Activate.ps1
python main.py

3) Subir o dashboard Flutter
cd dashboard_flutter
flutter pub get
flutter run -d chrome

Alternativa para ambientes limitados
------------------------------------
Se o dashboard Flutter tiver dificuldade para abrir com o target Chrome em máquinas mais antigas ou limitadas, use o modo Web Server:

cd dashboard_flutter
flutter run -d web-server --web-port 8080

Há também um inicializador dedicado para esse cenário:
- start_all_WebServer.bat

Execução automatizada no Windows
--------------------------------
Scripts disponíveis na raiz do projeto:
- start_all.bat
- stop_all.bat
- start_all_WebServer.bat

Uso típico:
- start_all.bat: sobe API, recorder e dashboard no fluxo padrão.
- stop_all.bat: encerra as janelas/processos da suíte.
- start_all_WebServer.bat: sobe o agente com o dashboard via Web Server.

Fluxo do sistema
----------------
1. O bot entra no canal do Discord.
2. O bot grava a reunião.
3. O áudio é salvo localmente.
4. O arquivo temporário é convertido para .ogg.
5. O recorder envia meeting_id e audio_path para a API.
6. A API:
   - transcreve o áudio;
   - classifica a reunião;
   - gera a ata.
7. O resultado final é salvo em minutes_api/data/minutes/.
8. O dashboard permite listar e visualizar as reuniões.

Endpoints principais da API
---------------------------
- GET  /health
- POST /gerar-ata
- POST /process-meeting
- GET  /meetings

Observações sobre integração:
- O endpoint manual /gerar-ata recebe o campo transcript.
- A geração automática de atas depende de POST /process-meeting.
- Recomenda-se acrescentar GET /meetings/<meeting_id> para suportar abertura de uma reunião específica no dashboard.

Dashboard
---------
O dashboard evoluiu de um fluxo puramente manual para um modelo híbrido:
- listagem de reuniões;
- visualização de atas;
- fluxo manual preservado como alternativa.

Troubleshooting
---------------
Erro: ModuleNotFoundError: No module named flask
- Instale as dependências da API:
  cd minutes_api
  .\.venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt

Erro: HTTPConnectionPool(host=127.0.0.1, port=5000)
- A API não está rodando. Inicie primeiro o python app.py dentro de minutes_api.

Erro: ffmpeg não encontrado no PATH
- Instale o FFmpeg completo e adicione a pasta bin ao PATH do Windows (tutorial específico em https://youtu.be/RNf8I2nxFKw?si=LD54cNyUhACokO_X).
- Valide com os comandos abaixo no terminal:
  ffmpeg -version
  ffprobe -version

Erro: flutter não reconhecido
- Verifique se o Flutter SDK está instalado e no PATH.
- Valide com:
  flutter --version
  flutter doctor
  flutter devices

Erro 404 ao finalizar a gravação
- Verifique se o recorder está chamando o endpoint correto da API, especialmente POST /process-meeting.

Estado atual do projeto
-----------------------
O projeto atingiu um estágio mais sólido, com:
- arquitetura mais modular;
- recorder menos acoplado;
- pipeline de áudio estável;
- integração com a API consolidada;
- dashboard funcional em ambiente web;
- melhor separação entre operação, persistência e processamento.

Conclusão
---------
O MeetMind deixou de ser um conjunto de scripts acoplados e passou a funcionar como um agente organizado, modular e operacionalmente mais previsível.
