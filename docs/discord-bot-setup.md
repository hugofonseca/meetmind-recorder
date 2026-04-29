# Configuração do Bot no Discord

## Criar bot
1) Discord Developer Portal → New Application
2) Bot → Add Bot
3) Copie o token e configure no `.env` como `DISCORD_TOKEN=...`

## Intents recomendadas
- Message Content
- Voice States
- Members

## Permissões no servidor
Recomendado:
- View Channels
- Send Messages
- Connect / Speak
- Manage Channels (para criar canal `meeting-transcription-...`)