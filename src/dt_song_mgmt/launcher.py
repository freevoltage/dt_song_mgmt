"""macOS project picker and background server management for the app launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .project import read_project


APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Elektron Digi Song Mode Manager"
LOG_DIR = Path.home() / "Library" / "Logs" / "Elektron Digi Song Mode Manager"
REGISTRY = APP_SUPPORT / "launcher-processes.json"


def _osascript(source: str) -> str:
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", source],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        # AppleScript returns a nonzero status when a user cancels a chooser.
        return ""
    return result.stdout.strip()


def _dialog(message: str) -> None:
    escaped = message.replace("\r", " ").replace("\n", " ").replace("\\", "\\\\").replace('"', '\\"')
    _osascript(f'display dialog "{escaped}" buttons {{"OK"}} default button "OK"')


def _read_registry() -> list[dict]:
    try:
        records = json.loads(REGISTRY.read_text())
        return records if isinstance(records, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _process_command(pid: int) -> str | None:
    try:
        return subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _matches_launcher_record(record: dict) -> bool:
    try:
        pid = int(record["pid"])
        project = str(record["project"])
    except (KeyError, TypeError, ValueError):
        return False
    command = _process_command(pid)
    return bool(command and "dt_song_mgmt.cli" in command and project in command)


def stop_servers() -> int:
    """Stop only live DSM web servers created by this launcher."""
    stopped = 0
    remaining = []
    for record in _read_registry():
        try:
            pid = int(record["pid"])
            project = str(record["project"])
        except (KeyError, TypeError, ValueError):
            continue
        command = _process_command(pid)
        if not command or "dt_song_mgmt.cli" not in command or project not in command:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        for _ in range(30):
            time.sleep(0.1)
            if _process_command(pid) is None:
                break
        else:
            # Recheck identity before force-stopping in case the PID was reused.
            if project in (_process_command(pid) or ""):
                os.kill(pid, signal.SIGKILL)
        stopped += 1

    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    temp_registry = REGISTRY.with_suffix(".tmp")
    temp_registry.write_text(json.dumps(remaining, indent=2))
    temp_registry.replace(REGISTRY)
    return stopped


def _choose_project() -> Path | None:
    result = _osascript(
        'set projectFile to choose file with prompt "Choose a Digitakt II or Digitone II project"\n'
        'return POSIX path of projectFile'
    )
    if not result:
        return None
    project = Path(result).expanduser().resolve()
    if project.suffix.lower() not in {".dt2prj", ".dn2prj"}:
        _dialog("Choose a .dt2prj or .dn2prj project file.")
        return None
    if not project.is_file():
        _dialog(f"Project file not found: {project}")
        return None
    try:
        read_project(project)
    except Exception as exc:
        _dialog(f"Could not open project:\n{exc}")
        return None
    return project


def _start_server(project: Path) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{project.stem}.log"
    code = "from dt_song_mgmt.cli import main; main(__import__('sys').argv[1:])"
    command = [sys.executable, "-c", code, "dsm-launcher", str(project), "web"]
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    time.sleep(0.15)
    if process.poll() is not None:
        _dialog(f"DSM could not start. Details are in:\n{log_path}")
        return

    records = [record for record in _read_registry() if _matches_launcher_record(record)]
    records.append({"pid": process.pid, "project": str(project)})
    temp_registry = REGISTRY.with_suffix(".tmp")
    temp_registry.write_text(json.dumps(records, indent=2))
    temp_registry.replace(REGISTRY)


def launch() -> None:
    """Show the launcher menu and start/stop app-managed project servers."""
    if sys.platform != "darwin":
        raise SystemExit("The graphical launcher is available on macOS only.")
    action = _osascript(
        'set selectedAction to choose from list {"Open a project", "Stop app-launched servers"} '
        'with prompt "Elektron Digi Song Mode Manager" default items {"Open a project"}\n'
        'if selectedAction is false then return ""\n'
        'return item 1 of selectedAction'
    )
    if action == "Stop app-launched servers":
        count = stop_servers()
        _dialog(f"Stopped {count} DSM server{'s' if count != 1 else ''} launched by the app.")
    elif action == "Open a project":
        project = _choose_project()
        if project is not None:
            _start_server(project)
