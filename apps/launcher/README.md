# CalcChain Launcher Widget

Small desktop launcher for CalcChain.

## Run from repository

From the repository root:

```bat
.venv\Scripts\python.exe apps\launcher\calcchain_launcher.py
```

The launcher expects these paths relative to the application root:

```text
web\index.html
plugins\
caddy\caddy.exe
caddy\Caddyfile.lan
```

## Modes

- `Local`: starts only the backend at `http://127.0.0.1:8765/`.
- `LAN`: starts the backend at `127.0.0.1:8765`, starts Caddy at `https://<LAN-IP>:8443/`, and generates a one-time pairing code.

The LAN IP can be overridden before launch:

```bat
set CALCCHAIN_LAN_IP=192.168.0.3
.venv\Scripts\python.exe apps\launcher\calcchain_launcher.py
```

## Build EXE later

Example PyInstaller command:

```bat
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name CalcChainLauncher apps\launcher\calcchain_launcher.py
```

For the installed layout, place `CalcChainLauncher.exe` in the CalcChain application root next to `web`, `plugins`, `python`, and `caddy`.
