"""Exercise the real launcher / frozen EXE without API keys or external services."""

import argparse
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


BASE = 'http://127.0.0.1:8000'


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, body=None, method=None, expected=200):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(BASE + path, data=data, method=method,
                                         headers={'Content-Type': 'application/json'})
        try:
            response = self.opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            assert response.status == expected, (path, response.status, content[:500])
            return content, response.headers

    def json(self, path, body=None, method=None):
        return json.loads(self.request(path, body, method)[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--archive', type=Path)
    mode.add_argument('--web', action='store_true', help='Test the ordinary web server without desktop overrides')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='PaperReader smoke ') as temp:
        base = Path(temp) / '中文 portable path'
        base.mkdir()
        if args.archive:
            with zipfile.ZipFile(args.archive) as archive:
                names = archive.namelist()
                assert not any(name.startswith('data/') or name.endswith('paperreader.db') for name in names)
                archive.extractall(base)
            command = [str(base / 'PaperReader.exe')]
            assert (base / 'config.env').is_file()
        elif args.web:
            command = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000']
        else:
            command = [sys.executable, str(root / 'desktop' / 'launcher.py')]
        env = os.environ.copy()
        env.update(PAPERREADER_NO_WINDOW='1', DATA_DIR=str(base / '用户数据'),
                   PAPERREADER_ENV_FILE=str(base / 'config.env'), AUTH_SECRET_KEY='smoke-test-only',
                   OPENAI_API_KEY='', MINERU_API_KEY='', PDF_PARSER='local')
        if args.web:
            env['PYTHONPATH'] = str(root / 'backend')
            env.pop('PAPERREADER_FRONTEND_DIR', None)
        processes = []

        def start():
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', 8000))
            process = subprocess.Popen(command, cwd=base, env=env)
            processes.append(process)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    error_log = base / 'PaperReader-error.log'
                    raise RuntimeError(error_log.read_text(encoding='utf-8') if error_log.exists()
                                       else f'Launcher exited: {process.returncode}')
                try:
                    health = Client().json('/health')
                    assert health['app'] == 'PaperReader' and health['version'] == '2.0.0'
                    return process
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(0.25)
            raise TimeoutError('Packaged backend did not become healthy')

        def stop(process):
            process.terminate()
            process.wait(timeout=20)

        try:
            process = start()
            first, second = Client(), Client()
            html, _ = first.request('/')
            js_paths = re.findall(r'src="([^"]+\.js)"', html.decode())
            assert js_paths, 'Built frontend did not load'
            for path in js_paths:
                javascript, headers = first.request(path)
                assert 'javascript' in headers['Content-Type']
                assert b'http://localhost:8000' not in javascript, 'Production UI must use same-origin API'
            if args.archive:
                workers = [name for name in names if 'frontend_dist/assets/' in name and name.endswith('.mjs')]
            else:
                workers = list((root / 'frontend' / 'dist' / 'assets').glob('*.mjs'))
            assert workers, 'PDF.js worker missing'
            for worker in workers:
                _, headers = first.request('/assets/' + Path(worker).name)
                assert 'javascript' in headers['Content-Type']
            first.request('/api/documents', expected=401)
            owner = first.json('/api/auth/register', {'username': 'smoke-owner', 'password': 'smoke-password'})
            second.json('/api/auth/register', {'username': 'smoke-other', 'password': 'smoke-password'})
            assert first.json('/api/auth/me')['id'] == owner['id']
            first.json('/api/settings/me', {'theme': 'dark', 'api_key': 'local-test-key'}, 'PUT')
            session = first.json('/api/chat/sessions', {'scope': 'library', 'title': 'Smoke conversation'})
            second.request('/api/chat/sessions/' + session['session_id'], expected=404)
            first.request('/data/paperreader.db', expected=404)
            first.request('/data/chat_sessions.json', expected=404)
            # Upload a source without calling the LLM: invalid file types are
            # rejected, and a blank PDF can be persisted for reading.
            boundary = 'PaperReaderSmokeBoundary'
            from pypdf import PdfWriter
            from io import BytesIO
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            pdf = BytesIO()
            writer.write(pdf)
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke.pdf"\r\n'
                    'Content-Type: application/pdf\r\n\r\n').encode() + pdf.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
            request = urllib.request.Request(BASE + '/api/upload', data=body,
                                             headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
            with first.opener.open(request, timeout=20) as response:
                document_id = json.load(response)['document_id']
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                document = first.json('/api/document/' + document_id)
                if document['status'] in ('done', 'failed'):
                    break
                time.sleep(0.2)
            assert document['status'] in ('done', 'failed'), 'Upload pipeline did not settle'
            second.request('/api/document/' + document_id, expected=404)
            source_url = '/data/outputs/' + document_id + '/original.pdf'
            content, _ = first.request(source_url)
            assert content.startswith(b'%PDF')
            second.request(source_url, expected=404)
            stop(process)
            process = start()
            assert first.json('/api/auth/me')['settings']['theme'] == 'dark'
            assert first.json('/api/auth/me')['settings']['api_key'] == 'local-test-key'
            assert first.json('/api/documents')[0]['document_id'] == document_id
            assert first.json('/api/chat/sessions/' + session['session_id'])['title'] == 'Smoke conversation'
            first.json('/api/auth/logout', {}, 'POST')
            first.request('/api/auth/me', expected=401)
            first.json('/api/auth/login', {'username': 'smoke-owner', 'password': 'smoke-password'})
            assert first.json('/api/auth/me')['id'] == owner['id']
            print('PASS: frontend, PDF worker MIME, cookies, upload/read, user isolation, profile, chat persistence, restart, login/logout')
        finally:
            for process in processes:
                if process.poll() is None:
                    stop(process)


if __name__ == '__main__':
    main()
