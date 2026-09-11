# Install — Windows Server / PC

Requiere: PowerShell 5+, CPython oficial 3.12+ (`winget install Python.Python.3.12`). **No** usar el alias `python` de Microsoft Store.

```powershell
git clone https://github.com/fronteraespacial/universal-bot.git
cd universal-bot
Set-ExecutionPolicy -Scope Process Bypass
.\install\windows\install.ps1 -Instance mi-sitio
```

Editar `C:\universal-bot\instances\mi-sitio\instance.toml`.

Pegar el token en `%USERPROFILE%\.config\universal-bot\mi-sitio.env` (icacls dueño).

```powershell
py -3 -m pip install -U discord.py pytest
```

No matar AnyDesk / Sunshine / Tailscale al cablear el bot. No `tscon` a ciegas.
