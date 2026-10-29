import sqlite3
import sys
import time

import pytest

from learning.db import Store


class FakeVault:
    available = True

    def __init__(self, key=None):
        self.key = key

    def load(self):
        return self.key

    def save(self, key):
        self.key = key

    def delete(self):
        self.key = None


def test_desktop_starts_real_service_without_console(tmp_path, monkeypatch):
    """Windowed EXEs have no stdout/stderr; double-click must serve HTTP and the web exit must stop it."""
    import threading
    import desktop
    import httpx
    import uvicorn

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setattr(desktop, 'legacy_root', lambda: tmp_path / 'empty')
    # Keep the customer's saved credentials and any running 8877 service untouched.
    vault = FakeVault('offline-startup-test-key')
    monkeypatch.setattr(desktop, 'WindowsVault', lambda: vault)
    monkeypatch.setattr(desktop, 'port_busy', lambda port=8877: False)
    original_config = uvicorn.Config

    def isolated_config(*args, **kwargs):
        kwargs['port'] = 0
        return original_config(*args, **kwargs)

    monkeypatch.setattr(uvicorn, 'Config', isolated_config)
    opened, alerts, servers = [], [], []
    monkeypatch.setattr(desktop.webbrowser, 'open', opened.append)
    monkeypatch.setattr(desktop, 'alert', alerts.append)
    original_build = desktop.build_service

    def capture(*args, **kwargs):
        application, server = original_build(*args, **kwargs)
        servers.append(server)
        return application, server

    monkeypatch.setattr(desktop, 'build_service', capture)
    result = []
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    worker = threading.Thread(target=lambda: result.append(desktop.main()), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not opened and time.monotonic() < deadline:
            time.sleep(0.05)
        assert opened == [desktop.URL], alerts
        server = servers[0]
        port = server.servers[0].sockets[0].getsockname()[1]
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
            assert client.get('/').status_code == 200
            status = client.get('/api/status').json()
            # The remembered key is applied at startup with no launcher window.
            assert status['configured'] is True and status['needs_setup'] is True
            assert client.get('/api/report').status_code == 200
            assert client.post('/api/auth/setup', json={'username': 'admin', 'password': 'offline-pass'}).status_code == 200
            assert client.post('/api/system/shutdown').status_code == 200
        worker.join(timeout=10)
        assert not worker.is_alive() and result == [0] and not alerts
    finally:
        if servers:
            servers[0].should_exit = True
        worker.join(timeout=5)
        assert (tmp_path / 'appdata' / 'ZhixingLearningStudio' / 'learning.sqlite').is_file()


def test_second_launch_reopens_running_service(monkeypatch):
    import desktop

    opened = []
    monkeypatch.setattr(desktop, 'port_busy', lambda port=8877: True)
    monkeypatch.setattr(desktop, 'our_service_running', lambda url=desktop.URL: True)
    monkeypatch.setattr(desktop.webbrowser, 'open', opened.append)
    assert desktop.main() == 0 and opened == [desktop.URL]


def test_offline_password_reset_recovers_a_locked_out_admin(tmp_path, monkeypatch):
    import desktop
    from learning.accounts import Accounts

    database = tmp_path / 'learning.sqlite'
    accounts = Accounts(Store(database))
    admin = accounts.setup_admin('Admin', 'forgotten-pass')
    token, _ = accounts.login('Admin', 'forgotten-pass')
    messages = []
    monkeypatch.setattr(desktop, 'alert', lambda message, error=True: messages.append((message, error)))
    assert desktop.reset_command('admin', database) == 0
    temporary = messages[-1][0].split('：')[1].split('\n')[0]
    assert messages[-1][1] is False and accounts.login('Admin', temporary)[1]['id'] == admin['id']
    # Existing sessions signed in with the forgotten password no longer work.
    assert accounts.user_for_token(token) is None
    assert desktop.reset_command('nobody', database) == 1 and messages[-1][1] is True
    assert desktop.reset_command('admin', tmp_path / 'missing.sqlite') == 1


def test_foreign_port_owner_is_reported(monkeypatch):
    import desktop

    alerts = []
    monkeypatch.setattr(desktop, 'port_busy', lambda port=8877: True)
    monkeypatch.setattr(desktop, 'our_service_running', lambda url=desktop.URL: False)
    monkeypatch.setattr(desktop, 'alert', alerts.append)
    assert desktop.main() == 1 and '8877' in alerts[0]


def test_prepare_data_uses_per_user_directory_and_migrates_once(tmp_path, monkeypatch):
    from desktop import prepare_data

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
    legacy = tmp_path / 'source' / 'data' / 'learning.sqlite'
    Store(legacy).put('courses', 'saved', {'id': 'saved', 'title': 'Original'})
    target = prepare_data(tmp_path / 'source')
    assert target == tmp_path / 'appdata' / 'ZhixingLearningStudio' / 'learning.sqlite'
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM documents WHERE kind='courses'").fetchone()[0] == 1
    Store(legacy).put('courses', 'new', {'id': 'new', 'title': 'Later'})
    assert prepare_data(tmp_path / 'source') == target
    assert len(Store(target).list('courses')) == 1


def test_prepare_data_requires_windows_user_directory(tmp_path, monkeypatch):
    from desktop import prepare_data

    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    with pytest.raises(RuntimeError, match='LOCALAPPDATA'):
        prepare_data(tmp_path)


def test_frozen_release_finds_local_legacy_checkout(tmp_path, monkeypatch):
    import desktop

    checkout = tmp_path / 'rebuild'
    executable = checkout / 'release' / 'app' / 'ZhixingLearningStudio' / 'ZhixingLearningStudio.exe'
    monkeypatch.setattr(desktop.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(desktop.sys, 'executable', str(executable))
    assert desktop.legacy_root() == checkout


def test_vault_rejects_empty_key():
    from credential_vault import save_key

    with pytest.raises(ValueError):
        save_key('  ')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Credential Manager only')
def test_vault_roundtrip_isolated_target(monkeypatch):
    import credential_vault

    monkeypatch.setattr(credential_vault, 'TARGET', 'ZhixingLearningStudio/test-only')
    credential_vault.delete_key()
    try:
        credential_vault.save_key('test-only-not-a-secret')
        assert credential_vault.load_key() == 'test-only-not-a-secret'
    finally:
        credential_vault.delete_key()
    assert credential_vault.load_key() is None
