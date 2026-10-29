"""Windows launcher: starts the local service and opens the web interface. No setup window."""
from __future__ import annotations

import os
import multiprocessing
import json
import secrets
import socket
import sqlite3
import sys
import threading
import time
import tempfile
from pathlib import Path
import webbrowser

from credential_vault import WindowsVault

APP_NAME = 'ZhixingLearningStudio'
URL = 'http://127.0.0.1:8877/'
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def data_path() -> Path:
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise RuntimeError('缺少 Windows LOCALAPPDATA 用户目录。')
    return Path(base) / APP_NAME / 'learning.sqlite'


def prepare_data(source_root: Path = RESOURCE_ROOT) -> Path:
    target = data_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = Path(source_root) / 'data' / 'learning.sqlite'
    if not target.exists() and legacy.is_file():
        # SQLite backup also captures committed data in a live WAL database.
        with sqlite3.connect(legacy) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    return target


def log_dir() -> Path:
    return data_path().parent / 'logs'


def legacy_root() -> Path:
    if getattr(sys, 'frozen', False):
        # Local source checkout beside release/ may have existing learning data.
        parents = Path(sys.executable).resolve().parents
        if len(parents) > 3:
            candidate = parents[3]
            if candidate.name.lower() == 'rebuild':
                return candidate
    return RESOURCE_ROOT


def create_server(application, port: int = 8877):
    import uvicorn

    # PyInstaller --windowed sets stdout/stderr to None. Uvicorn's default
    # logging formatters probe stdout.isatty(), failing before the server starts.
    config = uvicorn.Config(application, host='127.0.0.1', port=port,
                            access_log=False, log_level='warning', log_config=None)
    return uvicorn.Server(config)


def build_service(database: Path, vault=None, port: int = 8877):
    """Create the app and server; the web 'exit' button stops this server."""
    from learning.api import create_app
    application = create_app(db_path=database, vault=vault)
    server = create_server(application, port)
    application.state.shutdown = lambda: setattr(server, 'should_exit', True)
    return application, server


def open_when_ready(server, url: str = URL, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.1)
    if server.started:
        webbrowser.open(url)
    return server.started
def self_test(output: Path) -> None:
    from fastapi.testclient import TestClient
    from learning.api import create_app
    from learning.version import VERSION
    from learning.mathcheck import verify_answer
    checks = {
        'frontend': (RESOURCE_ROOT / 'frontend' / 'dist' / 'index.html').is_file(),
        'knowledge': (RESOURCE_ROOT / 'knowledge' / 'calculus.json').is_file(),
        'report': (RESOURCE_ROOT / 'docs' / '项目汇报.html').is_file(),
        'math_process': verify_answer('x+x', '2*x', variables=['x'])['status'] == 'verified',
    }
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(db_path=Path(directory) / 'test.sqlite')) as client:
            checks['http_home'] = client.get('/').status_code == 200
            checks['http_status'] = client.get('/api/status').json().get('version') == VERSION
            checks['http_report'] = client.get('/api/report').status_code == 200
        from learning.logs import log, setup
        log_file = setup(Path(directory) / 'logs')
        log.error('self-test key sk-%s', 'a' * 24)
        for handler in log.handlers: handler.flush()
        text = log_file.read_text(encoding='utf-8') if log_file.is_file() else ''
        checks['log_redacted'] = 'self-test key [REDACTED]' in text and 'a' * 24 not in text
        for handler in list(log.handlers):
            handler.close(); log.removeHandler(handler)
        # Test the real desktop server path too, rather than TestClient alone.
        # An ephemeral port and temporary database leave customer data untouched.
        import httpx
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            _, server = build_service(Path(directory) / 'runtime.sqlite', port=port)
            worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 10
                while worker.is_alive() and not server.started and time.monotonic() < deadline:
                    time.sleep(0.05)
                checks['desktop_server_started'] = server.started
                if server.started:
                    with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                                      timeout=5) as client:
                        checks['runtime_http_home'] = client.get('/').status_code == 200
                        status = client.get('/api/status').json()
                        checks['runtime_http_status'] = status.get('version') == VERSION and status.get('needs_setup') is True
                        checks['runtime_http_report'] = client.get('/api/report').status_code == 200
                        checks['runtime_login_required'] = client.get('/api/courses').status_code == 401
                        setup = client.post('/api/auth/setup', json={'username': 'selftest', 'password': 'self-test-only'})
                        checks['runtime_setup'] = setup.status_code == 200
                        checks['runtime_session'] = client.get('/api/courses').status_code == 200
                        # Another local port must not reuse this session (same SameSite "site").
                        checks['runtime_cross_site_blocked'] = client.post(
                            '/api/auth/login', json={'username': 'x', 'password': 'y'},
                            headers={'Origin': 'http://127.0.0.1:5173'}).status_code == 403
                        # The web "exit" button must stop the real server, not just answer.
                        checks['runtime_shutdown_accepted'] = client.post('/api/system/shutdown').status_code == 200
                    worker.join(timeout=10)
                    checks['runtime_shutdown_stopped'] = not worker.is_alive()
            finally:
                server.should_exit = True
                worker.join(timeout=5)
                checks['desktop_server_stopped'] = not worker.is_alive()
    output.write_text(json.dumps(checks, ensure_ascii=False), encoding='utf-8')
    if not all(checks.values()):
        raise SystemExit(1)


def port_busy(port: int = 8877) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def our_service_running(url: str = URL) -> bool:
    import httpx
    from learning.version import VERSION
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            return client.get(url + 'api/status').json().get('version') == VERSION
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def alert(message: str, error: bool = True) -> None:
    # Windowed builds have no console; a native message box needs no extra dependency.
    if sys.platform == 'win32' and sys.stdout is None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, '知行 · AI 学习工作室', 0x10 if error else 0x40)
    else:
        stream = sys.stderr if error else sys.stdout
        if stream:
            print(message, file=stream)


def reset_password(database: Path, username: str) -> str:
    """Offline recovery for a forgotten password. Anyone able to run this already owns the data file."""
    if not database.is_file():
        raise FileNotFoundError(database)
    from learning.accounts import Accounts
    from learning.db import Store
    accounts = Accounts(Store(database))
    match = next((u for u in accounts.list() if u['username'].lower() == username.strip().lower()), None)
    if match is None:
        raise KeyError(username)
    temporary = secrets.token_urlsafe(9)
    accounts.set_password(match['id'], temporary)
    return temporary


def reset_command(username: str, database: Path | None = None) -> int:
    try:
        temporary = reset_password(database or data_path(), username)
    except KeyError:
        alert(f'没有找到账号“{username}”。')
        return 1
    except FileNotFoundError:
        alert('还没有学习数据：请先正常打开一次程序并创建管理员账号。')
        return 1
    except Exception as exc:
        alert(f'重置失败：{type(exc).__name__}。')
        return 1
    alert(f'已为“{username}”设置临时密码：{temporary}\n请立即登录，并在“设置”里改成自己的密码。该账号原有的登录已全部失效。',
          error=False)
    return 0


def main() -> int:
    if sys.platform != 'win32':
        print('desktop.py 是 Windows 桌面启动器；macOS/Linux 请运行 python scripts/serve.py。', file=sys.stderr)
        return 1
    if port_busy():
        # A second double-click just reopens the page of the running service.
        if our_service_running():
            webbrowser.open(URL)
            return 0
        alert('8877 端口已被其他程序或旧版服务占用。请关闭后重新打开。')
        return 1
    try:
        database = prepare_data(legacy_root())
        from learning.logs import log, setup
        setup(log_dir())
        log.info('service starting')
        _, server = build_service(database, WindowsVault())
    except Exception as exc:
        # Never include exception payloads from provider or credential operations.
        alert(f'无法启动本机服务：{type(exc).__name__}。')
        return 1
    threading.Thread(target=open_when_ready, args=(server,), daemon=True).start()
    try:
        server.run()
    except SystemExit:
        pass
    if not server.started:
        alert('服务未能启动。请检查 8877 端口和 Windows 安全设置。')
        return 1
    return 0


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        self_test(Path(sys.argv[2]))
    elif len(sys.argv) in (3, 4) and sys.argv[1] == '--reset-password':
        raise SystemExit(reset_command(sys.argv[2], Path(sys.argv[3]) if len(sys.argv) == 4 else None))
    else:
        raise SystemExit(main())
