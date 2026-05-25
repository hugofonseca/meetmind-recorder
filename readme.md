MeetMind — Atualização de operação
Este projeto foi reorganizado para funcionar como uma suíte com três partes: um bot do Discord para gravar reuniões, uma API Flask para transcrever e gerar atas, e um dashboard Flutter para visualizar e editar resultados.

Estrutura atual

A estrutura principal passou a usar minutes_api/ para o backend, recorder/ para o bot e dashboard_flutter/ para a interface gráfica.
O backend salva transcrições em data/transcripts/, chunks em data/chunks/ e atas em data/minutes/ dentro de minutes_api/.

Mudanças principais de hoje

O app.py foi ajustado para trabalhar com os diretórios locais do backend e expor os endpoints GET /health, POST /gerar-ata, POST /process-meeting e GET /meetings.
O endpoint manual /gerar-ata foi alinhado para receber o campo transcript, e não transcricao, o que exigiu também ajuste correspondente no Flutter para o modo manual.
A geração automática de atas pelo bot passou a depender de POST /process-meeting, que transcreve o .ogg, executa o pipeline de resumo/classificação e salva um arquivo *.minutes.json em minutes_api/data/minutes/.

Correções técnicas aplicadas

O problema de ausência de arquivos em data/minutes/ foi identificado como consequência de falha anterior no processamento antes da gravação final do JSON.
A integração com a Groq foi estabilizada após corrigir ambiente, dependências e compatibilidade de biblioteca HTTP para o fluxo de transcrição usado em transcriber.py.
O bot também teve o ambiente Python ajustado para instalar corretamente discord.py e demais dependências do requirements.txt antes da execução de main.py.

Dashboard mais prático

O dashboard original foi criado em fluxo manual, com campo para colar transcrição e botão para gerar ata via API.
A recomendação passou a ser evoluí-lo para um fluxo híbrido: lista de reuniões salvas à esquerda, abertura de uma ata específica via endpoint de detalhe e modo manual preservado como alternativa.
Para isso, o backend precisa usar a rota de detalhe GET /meetings/<meeting_id>, pois a versão antiga com @app.get("/meetings/") não permite recuperar uma reunião específica pelo identificador.

Operação diária

A operação normal agora acontece com três processos separados: API Flask, bot Discord e dashboard Flutter em modo web ou desktop.
Para reduzir atrito, foi proposta a criação de um script start_all.bat que abre os três terminais automaticamente usando os ambientes virtuais já preparados.
Este pacote inclui também stop_all.bat, que tenta encerrar as janelas abertas com os títulos minutes_api, recorder e dashboard para facilitar o encerramento da suíte no Windows.

Fluxo final esperado

Ao executar o bot e encerrar uma reunião no Discord, o áudio é salvo localmente, convertido e enviado para a API com meeting_id e audio_path.
A API transcreve o áudio, classifica a reunião, gera a ata e grava o resultado em minutes_api/data/minutes/, tornando o conteúdo disponível para listagem em GET /meetings e leitura detalhada no dashboard.