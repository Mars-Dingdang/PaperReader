import uuid
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.core.config import settings
from app.core.database import init_database
from app.main import app
from app.models import store
from app.services import auth_service, legacy_import


def register(client, username):
    response = client.post('/api/auth/register', json={'username': username, 'password': 'test-password'})
    assert response.status_code == 200, response.text
    return response.json()


def test_accounts_documents_and_settings_survive_restart(isolated_storage):
    with TestClient(app) as first, TestClient(app) as other:
        user = register(first, 'legacy-owner')
        register(other, 'other-owner')
        response = first.put('/api/settings/me', json={'api_key': 'test-only-key', 'theme': 'dark'})
        assert response.status_code == 200
        source = settings.upload_dir / 'existing.tex'
        source.write_text('Existing TeX source')
        record = store.DocumentRecord('existing-doc', user['id'], 'tex', source, source_filename='existing.tex')
        store.save_document(record)
        store.DOCUMENTS.clear()
        init_database()
        assert first.get('/api/auth/me').json()['settings']['api_key'] == 'test-only-key'
        assert first.get('/api/auth/me').json()['settings']['theme'] == 'dark'
        assert first.get('/api/documents').json()[0]['document_id'] == 'existing-doc'
        assert other.get('/api/documents').json() == []
        assert other.get('/api/document/existing-doc').status_code == 404
        assert first.get('/data/uploads/existing.tex').text == 'Existing TeX source'
        assert other.get('/data/uploads/existing.tex').status_code == 404
        assert first.get('/data/paperreader.db').status_code == 404
        first.post('/api/auth/logout')
        assert first.get('/data/uploads/existing.tex').status_code == 401


def test_legacy_import_is_explicit_idempotent_and_preserves_files(isolated_storage):
    auth_service.register_user('legacy-owner', 'test-password')
    other = auth_service.register_user('other-owner', 'test-password')
    document_id = str(uuid.uuid4())
    folder = settings.output_dir / document_id
    folder.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    original = buffer.getvalue()
    (folder / 'original.pdf').write_bytes(original)
    (folder / 'translated.pdf').write_bytes(original)
    (folder / 'translated.tex').write_text('Existing translated source')
    assert legacy_import.import_legacy_outputs('legacy-owner')[0]['status'] == 'would import'
    assert store.get_document(document_id) is None
    assert legacy_import.import_legacy_outputs('legacy-owner', apply=True)[0]['status'] == 'imported'
    assert store.get_document(document_id).translated_pdf_url.endswith('/translated.pdf')
    assert legacy_import.import_legacy_outputs('other-owner', apply=True)[0]['status'] == 'already indexed'
    assert store.list_documents_for_user(other.id) == []
    assert (folder / 'original.pdf').read_bytes() == original
    assert (folder / 'translated.tex').read_text() == 'Existing translated source'


def test_artifact_download_does_not_allow_symlink_escape(isolated_storage, tmp_path):
    with TestClient(app) as client:
        user = register(client, 'artifact-owner')
        folder = settings.output_dir / 'doc'
        folder.mkdir()
        source = folder / 'original.pdf'
        source.write_bytes(b'PDF fixture')
        store.save_document(store.DocumentRecord('doc', user['id'], 'pdf', source))
        assert client.get('/data/outputs/doc/original.pdf').content == b'PDF fixture'
        try:
            (folder / 'database.pdf').symlink_to(settings.data_dir / settings.sqlite_db_name)
        except OSError:
            return  # Windows runners without symlink privilege still test ordinary ownership.
        assert client.get('/data/outputs/doc/database.pdf').status_code == 404


def test_legacy_chat_request_shape_still_works_after_login(isolated_storage, monkeypatch):
    from app.api import routes_chat
    monkeypatch.setattr(routes_chat, 'search_online_literature', lambda message: [])
    monkeypatch.setattr(routes_chat.llm_client, 'chat', lambda **kwargs: 'A test answer')
    with TestClient(app) as client, TestClient(app) as other:
        user = register(client, 'chat-owner')
        register(other, 'chat-other')
        source = settings.upload_dir / 'paper.tex'
        source.write_text('Example paper')
        store.save_document(store.DocumentRecord('chat-doc', user['id'], 'tex', source, extracted_text='Example paper'))
        result = client.post('/api/chat', json={'document_id': 'chat-doc', 'message': 'Summarize'})
        assert result.status_code == 200, result.text
        assert result.json()['answer'].startswith('A test answer')
        session_id = result.json()['session_id']
        assert client.get(f'/api/chat/sessions/{session_id}').status_code == 200
        assert other.get(f'/api/chat/sessions/{session_id}').status_code == 404


def test_desktop_health_version():
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok', 'app': 'PaperReader', 'version': '2.0.0'}


def test_v1_mineru_configuration_keeps_its_parser(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv('PDF_PARSER', raising=False)
    assert Settings(_env_file=None, MINERU_API_KEY='legacy-test-key').pdf_parser == 'mineru'
    assert Settings(_env_file=None, MINERU_API_KEY='').pdf_parser == 'local'
    assert Settings(_env_file=None, MINERU_API_KEY='legacy-test-key', PDF_PARSER='local').pdf_parser == 'local'
