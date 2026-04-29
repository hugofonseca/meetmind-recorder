# Troubleshooting

## venv não ativa no PowerShell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1

## Bot online, mas sem transcrição
Use Stage Channel (📌 Meeting Room (Transcrição)).
Verifique permissões de voz (Connect/Speak).
Verifique se o bot criou o canal meeting-transcription-....

## Fallback disparou em canal de voz normal
Isso é esperado em alguns cenários.
Entre no Stage e rode !start_meeting novamente.