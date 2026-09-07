from app.services import chat_store


def test_chat_sessions_are_isolated_by_user(tmp_path, monkeypatch):
    store_path = tmp_path / "chat_sessions.json"
    monkeypatch.setattr(chat_store, "_STORE_PATH", store_path)

    first = chat_store.create_session(
        owner_user_id=101,
        scope="document",
        document_ids=["doc-a"],
    )
    second = chat_store.create_session(
        owner_user_id=202,
        scope="document",
        document_ids=["doc-b"],
    )

    assert chat_store.get_session(first["session_id"], owner_user_id=101)
    assert chat_store.get_session(first["session_id"], owner_user_id=202) is None
    assert [item["session_id"] for item in chat_store.list_sessions(
        owner_user_id=101,
        scope="document",
    )] == [first["session_id"]]
    assert [item["session_id"] for item in chat_store.list_sessions(
        owner_user_id=202,
        scope="document",
    )] == [second["session_id"]]

    try:
        chat_store.append_message(
            first["session_id"],
            owner_user_id=202,
            role="user",
            content="must not be accepted",
        )
    except KeyError:
        pass
    else:
        raise AssertionError("another user was able to write to this chat session")
