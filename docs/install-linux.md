# Install — Linux (VM / VPS / PC)

Requiere: `bash`, `python3` 3.12+, usuario con sudo si el prefijo es `/opt/universal-bot`.

```bash
git clone https://github.com/fronteraespacial/universal-bot.git
cd universal-bot
sudo mkdir -p /opt/universal-bot
sudo chown "$USER:$USER" /opt/universal-bot
bash install/linux/install.sh mi-sitio
```

Editar `/opt/universal-bot/instances/mi-sitio/instance.toml`.

Pegar el token en `~/.config/universal-bot/mi-sitio.env` (`chmod 600`).

Instalar runtime:

```bash
python3 -m venv /opt/universal-bot/.venv
/opt/universal-bot/.venv/bin/pip install -U pip discord.py pytest
```

Un solo proceso gateway por token. Watchdog + heartbeat; no depender de `Restart=on-failure` con tope 3.
