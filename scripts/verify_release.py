"""Verify a customer ZIP the way a customer runs it: extract, frozen self-test, windowed double-click.

Uses a temporary LOCALAPPDATA and a no-op browser, so customer learning data is untouched.
It never writes Windows Credential Manager and never calls DeepSeek. A key saved there earlier
may be read at startup exactly like a real launch; responses never contain it.
Run: .venv/Scripts/python.exe scripts/verify_release.py release/<package>.zip
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8877'
sys.path.insert(0, str(ROOT))
from learning.version import VERSION  # noqa: E402  single source of the release version

# Customer data, logs and secrets must never ship inside the package.
LEAK_SUFFIXES = ('.sqlite', '.sqlite-wal', '.sqlite-shm', '.db', '.env', '.log', '.pem', '.key')
# certifi's public CA bundle is required for HTTPS to DeepSeek and holds no private key.
LEAK_ALLOWED = {'zhixinglearningstudio/_internal/certifi/cacert.pem'}


def port_free() -> bool:
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', 8877)) != 0


def wait(predicate, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def get_status():
    try:
        return httpx.get(URL + '/api/status', timeout=2, trust_env=False).json()
    except (httpx.HTTPError, ValueError):
        return None


def main(package: Path) -> int:
    checks: dict[str, object] = {}
    data = package.read_bytes()
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    checks['zip_bytes'] = len(data)
    checks['zip_sha256'] = hashlib.sha256(data).hexdigest().upper()
    checks['zip_has_no_database_or_env'] = not any(n.lower().endswith(LEAK_SUFFIXES) and n.lower() not in LEAK_ALLOWED for n in names)
    checks['zip_has_no_logs_or_data_dir'] = not any(part in ('logs', 'data', '.venv', 'node_modules')
                                                    for n in names for part in n.lower().split('/')[:-1])
    checks['zip_name_matches_version'] = VERSION in package.name
    checks['zip_has_no_defense_material'] = not any('defense-' in n or 'midterm-' in n for n in names)
    if not port_free():
        print('8877 端口已被占用，请先退出正在运行的学习工作室。', file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix='zhixing-release-'))
    try:
        with zipfile.ZipFile(package) as archive:
            archive.extractall(work / 'unpacked')
        exe = next((work / 'unpacked').rglob('ZhixingLearningStudio.exe'))
        result = work / 'self-test.json'
        code = subprocess.run([str(exe), '--self-test', str(result)], timeout=180).returncode
        self_test = json.loads(result.read_text(encoding='utf-8')) if result.exists() else {}
        checks['frozen_self_test_exit_0'] = code == 0
        checks['frozen_self_test_all_true'] = bool(self_test) and all(self_test.values())
        checks['frozen_self_test'] = self_test

        # Double-click path: no arguments, windowed EXE (stdout/stderr absent), fresh user directory.
        noop = work / 'noop-browser.cmd'
        noop.write_text('@exit /b 0\r\n', encoding='ascii')
        env = dict(os.environ, LOCALAPPDATA=str(work / 'appdata'), BROWSER=str(noop))
        env.pop('DEEPSEEK_API_KEY', None)
        app = subprocess.Popen([str(exe)], env=env, cwd=exe.parent)
        try:
            checks['double_click_started'] = wait(lambda: (get_status() or {}).get('version') == VERSION, 60)
            status = get_status() or {}
            checks['double_click_needs_setup'] = status.get('needs_setup') is True
            checks['double_click_database_in_user_dir'] = (work / 'appdata' / 'ZhixingLearningStudio' / 'learning.sqlite').is_file()
            checks['double_click_log_dir_created'] = (work / 'appdata' / 'ZhixingLearningStudio' / 'logs').is_dir()
            # A second double-click must reopen the page and exit, not start another server.
            second = subprocess.run([str(exe)], env=env, cwd=exe.parent, timeout=30)
            checks['second_launch_exits_0'] = second.returncode == 0
            with httpx.Client(base_url=URL, trust_env=False, timeout=10) as client:
                checks['login_required'] = client.get('/api/courses').status_code == 401
                setup = client.post('/api/auth/setup', json={'username': 'release-check', 'password': 'release-check-1'})
                checks['setup_creates_admin'] = setup.status_code == 200
                checks['session_works'] = client.get('/api/courses').status_code == 200
                backup = client.get('/api/admin/backup')
                checks['admin_backup_is_sqlite'] = backup.status_code == 200 and backup.content[:16] == b'SQLite format 3\x00'
                checks['admin_progress_available'] = client.get('/api/admin/progress').status_code == 200
                checks['cross_site_blocked'] = client.post('/api/system/shutdown',
                                                           headers={'Origin': 'http://127.0.0.1:5173'}).status_code == 403
                checks['web_exit_accepted'] = client.post('/api/system/shutdown', headers={'Origin': URL}).status_code == 200
            try:
                checks['web_exit_stops_process'] = app.wait(timeout=20) == 0
            except subprocess.TimeoutExpired:
                checks['web_exit_stops_process'] = False
        finally:
            if app.poll() is None:
                app.kill()
                app.wait(timeout=10)
        checks['port_released'] = wait(port_free, 10)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    passed = all(v for k, v in checks.items() if isinstance(v, bool))
    report = {'kind': 'windows_release_check', 'version': VERSION, 'package': package.name,
              'at': datetime.now(timezone.utc).isoformat(), 'ok': passed,
              'method': '临时目录解压；冻结 EXE --self-test；无参数启动（窗口模式，无控制台）+ 真实本机 HTTP；临时 LOCALAPPDATA；不写凭据管理器；未调用 DeepSeek。',
              'limits': '在开发电脑上运行，不等于全新 Windows 客户机验收。', 'checks': checks}
    out = ROOT / 'release' / f'release-check-{VERSION}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in checks.items():
        if isinstance(v, bool):
            print(('PASS ' if v else 'FAIL ') + k)
    print(f'ZIP {checks["zip_bytes"]:,} 字节  SHA256 {checks["zip_sha256"]}')
    print('发布检查全部通过' if passed else '发布检查未通过')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
