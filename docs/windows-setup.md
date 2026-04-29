# Windows Setup

## Ativar venv no PowerShell
O PowerShell pode bloquear scripts. Para liberar apenas nesta sessão:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\.venv\Scripts\Activate.ps1