# PySolverLauncher

A Python-based utility to manage and auto-update Windows command-line solvers (e.g., `solver_fast.exe`).

## Features

- **Dynamic Executable Parsing**: Automatically parses the executable name from `cmd.txt`.
- **Auto Suffix Handling**: Automatically appends the `.exe` suffix if missing in the configuration.
- **Separate Console Window**: Runs the solver in its own console window via `CREATE_NEW_CONSOLE` to keep logs clean and separate.
- **Auto-Update Detection**: A background thread checks for new versions at random intervals (1-3 minutes).
- **Efficient Version Tracking**: Uses a persistent `update.ver` file to track the last successfully applied update's SHA1 (ZIP-based), avoiding unnecessary downloads.
- **Safe Termination Logic**: Attempts graceful shutdown (CTRL_BREAK and `taskkill`) before falling back to force termination after a 15-second timeout.
- **Version Bundling/Backup**: Automatically renames and backups existing update ZIPs if their SHA1 differs from the new one.

## Quick Start

### 1. Install Dependencies
Ensure you have Python 3.x and the `requests` library installed:
```bash
pip install -r requirements.txt
```

### 2. Configure `cmd.txt`
Create a `cmd.txt` file in the same directory as the script and add your solver's full execution command.
Example:
```text
solver_fast.exe --server ecdlp.protect.cx --worker-name "WhoCares" --gpu-limit 100 --resume
```
*Note: If you only provide `solver_fast`, the script will automatically look for `solver_fast.exe`.*

### 3. Run the Launcher
```bash
python launcher.py
```

## Update Mechanism

The script periodically checks the following endpoint:
`https://HOST/api/download-info` (where HOST is extracted from the `--server` argument in `cmd.txt`).

If the remote `sha1` differs from the version stored in `update.ver`, the script will:
1. Download the new ZIP bundle from `https://HOST/download/filename`.
2. Request the current solver to stop safely.
3. Extract and overwrite the files in the current directory.
4. Restart the solver with the original command.

## Important Notes
- The script relies on `cmd.txt` for initialization. Ensure it is correctly configured.
- `cmd.txt` is excluded from Git to prevent configuration conflicts or exposure of private settings.
