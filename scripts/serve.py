"""Cross-platform source launcher for 知行.

Windows users normally double-click the packaged EXE. This script is the
developer / macOS / Linux entry point: it serves the prebuilt frontend from
``frontend/dist`` on 127.0.0.1 and stores data in ``data/learning.sqlite``
unless ``--db`` or ``LEARNING_DB`` says otherwise. The DeepSeek key is entered
in the web settings page and kept in process memory for this run.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_PORT = 8877


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def running_version(port: int) -> str | None:
    import httpx
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(f'http://127.0.0.1:{port}/api/status')
        return response.json().get('version')
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def open_when_ready(server, url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.1)
    if server.started:
        webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='启动知行本机学习服务')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--db', default=os.getenv('LEARNING_DB', str(ROOT / 'data' / 'learning.sqlite')))
    parser.add_argument('--no-browser', action='store_true', help='只启动服务，不自动打开浏览器')
    args = parser.parse_args(argv)

    if sys.version_info < (3, 11):
        print('需要 Python 3.11 或更高版本。', file=sys.stderr)
        return 1
    try:
        import uvicorn
        from learning.api import create_app
        from learning.logs import setup as setup_logs
    except ImportError as exc:
        print(f'缺少依赖：{exc.name}。请先运行 pip install -r requirements.txt。', file=sys.stderr)
        return 1

    setup_logs(ROOT / 'logs')

    url = f'http://127.0.0.1:{args.port}/'
    if port_open(args.port):
        version = running_version(args.port)
        if version:
            print(f'知行已在 {url} 运行（版本 {version}），直接在浏览器打开即可。')
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f'端口 {args.port} 已被其他程序占用，请关闭后重试，或用 --port 换一个端口。', file=sys.stderr)
        return 2

    database = Path(args.db).expanduser().resolve()
    application = create_app(db_path=database)
    server = uvicorn.Server(uvicorn.Config(
        application, host='127.0.0.1', port=args.port, access_log=False, log_level='info'))
    application.state.shutdown = lambda: setattr(server, 'should_exit', True)

    print('知行 · 个性化多智能体学习工作室')
    print(f'地址：{url}')
    print(f'数据库：{database}')
    print('第一次打开时创建管理员账号；DeepSeek 密钥在“设置与账号”里填写。')
    print('按 Ctrl+C 或在网页里点“退出程序”即可停止服务。')
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(server, url), daemon=True).start()
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
