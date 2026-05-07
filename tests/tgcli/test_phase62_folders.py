import argparse
import asyncio

import pytest
from telethon.tl.types import DialogFilter, DialogFilterDefault, TextWithEntities

from tgcli.commands import chats
from tgcli.db import connect
from tgcli.safety import BadArgs


class FakeInputPeer:
    def __init__(self, peer_id):
        self.peer_id = int(peer_id)

    def to_dict(self):
        return {"_": "FakeInputPeer", "peer_id": self.peer_id}


def _seed_chat(path):
    con = connect(path)
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (123, "supergroup", "Alpha Forum", "alpha_forum"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (456, "user", "Beta User", "beta_user"),
    )
    con.execute(
        "INSERT INTO tg_chats(chat_id, type, title, username) VALUES (?, ?, ?, ?)",
        (789, "group", "Gamma Group", "gamma_group"),
    )
    con.commit()
    con.close()


def _title(text):
    return TextWithEntities(text=text, entities=[])


def _filter(folder_id=2, title="Ops", include=None, exclude=None):
    return DialogFilter(
        id=folder_id,
        title=_title(title),
        pinned_peers=[],
        include_peers=list(include or []),
        exclude_peers=list(exclude or []),
        contacts=True,
        non_contacts=False,
        groups=True,
        broadcasts=False,
        bots=False,
        exclude_muted=True,
        exclude_read=False,
        exclude_archived=False,
        emoticon="🗂",
    )


def _args(**kw):
    defaults = {
        "allow_write": True,
        "dry_run": False,
        "idempotency_key": "phase62-key",
        "fuzzy": False,
        "json": True,
        "human": False,
        "include_chat": [],
        "exclude_chat": [],
        "emoticon": None,
        "clear_include": False,
        "clear_exclude": False,
        "contacts": None,
        "non_contacts": None,
        "groups": None,
        "broadcasts": None,
        "bots": None,
        "exclude_muted": None,
        "exclude_read": None,
        "exclude_archived": None,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_folder_title_helpers_use_text_with_entities():
    title = chats._folder_title("Ops")
    assert isinstance(title, TextWithEntities)
    assert title.text == "Ops"
    assert title.entities == []
    assert chats._folder_title_text(title) == "Ops"


def test_folder_title_rejects_empty_string():
    with pytest.raises(BadArgs, match="folder title cannot be empty"):
        chats._folder_title("   ")


def test_folder_summary_marks_default_and_counts_peers():
    default = chats._folder_summary(DialogFilterDefault())
    assert default["folder_id"] == 0
    assert default["is_default"] is True
    assert default["type"] == "default"

    summary = chats._folder_summary(
        _filter(include=[FakeInputPeer(123), FakeInputPeer(456)], exclude=[FakeInputPeer(789)])
    )
    assert summary["folder_id"] == 2
    assert summary["title"] == "Ops"
    assert summary["emoticon"] == "🗂"
    assert summary["include_peer_count"] == 2
    assert summary["exclude_peer_count"] == 1
    assert summary["flags"]["contacts"] is True
    assert summary["flags"]["groups"] is True
    assert summary["flags"]["exclude_muted"] is True


def test_folders_list_uses_get_dialog_filters_request(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return [
                DialogFilterDefault(),
                _filter(folder_id=2, title="Ops", include=[FakeInputPeer(123)]),
                _filter(folder_id=3, title="Family", include=[FakeInputPeer(456)]),
            ]

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folders_list_runner(_args(query="op")))

    assert [folder["folder_id"] for folder in data["folders"]] == [2]
    assert data["folders"][0]["title"] == "Ops"
    request = fake.requests[0]
    assert request.__class__.__name__ == "GetDialogFiltersRequest"


def test_folder_show_enriches_peers_from_cache(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        async def start(self):
            pass

        async def __call__(self, request):
            return [
                DialogFilterDefault(),
                _filter(
                    folder_id=2,
                    title="Ops",
                    include=[FakeInputPeer(123), FakeInputPeer(999)],
                    exclude=[FakeInputPeer(456)],
                ),
            ]

        async def disconnect(self):
            pass

    monkeypatch.setattr(chats, "make_client", lambda session_path: FakeClient())
    data = asyncio.run(chats._folder_show_runner(_args(folder_id=2)))

    assert data["folder"]["folder_id"] == 2
    assert data["folder"]["include_peers"][0]["peer_id"] == 123
    assert data["folder"]["include_peers"][0]["cached"] is True
    assert data["folder"]["include_peers"][0]["title"] == "Alpha Forum"
    assert data["folder"]["include_peers"][0]["type"] == "supergroup"
    assert data["folder"]["include_peers"][1]["peer_id"] == 999
    assert data["folder"]["include_peers"][1]["cached"] is False
    assert data["folder"]["exclude_peers"][0]["title"] == "Beta User"


def test_folder_create_builds_dialog_filter_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []
            self.input_peer_calls = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [DialogFilterDefault(), _filter(folder_id=2, title="Existing")]
            return True

        async def get_input_entity(self, chat_id):
            self.input_peer_calls.append(chat_id)
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(
        title="Ops",
        emoticon="🗂",
        include_chat=[123],
        exclude_chat=[456],
        contacts=True,
        groups=True,
        exclude_muted=True,
        idempotency_key="folder-create-1",
    )

    first = asyncio.run(chats._folder_create_runner(args))
    second = asyncio.run(chats._folder_create_runner(args))

    assert first["folder_id"] == 3
    assert first["title"] == "Ops"
    assert first["include_peer_count"] == 1
    assert first["exclude_peer_count"] == 1
    assert second["folder_id"] == 3
    assert second["idempotent_replay"] is True
    assert [request.__class__.__name__ for request in fake.requests] == [
        "GetDialogFiltersRequest",
        "UpdateDialogFilterRequest",
    ]
    update = fake.requests[1]
    assert update.id == 3
    assert isinstance(update.filter.title, TextWithEntities)
    assert update.filter.title.text == "Ops"
    assert update.filter.emoticon == "🗂"
    assert update.filter.contacts is True
    assert update.filter.groups is True
    assert update.filter.exclude_muted is True
    assert fake.input_peer_calls == [123, 456]


def test_folder_create_dry_run_does_not_call_telethon(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    def fail_make_client(session_path):
        raise AssertionError("dry-run must not create Telethon client")

    monkeypatch.setattr(chats, "make_client", fail_make_client)
    data = asyncio.run(chats._folder_create_runner(_args(
        title="Ops",
        include_chat=[123],
        dry_run=True,
        idempotency_key="folder-create-dry-run",
    )))

    assert data["dry_run"] is True
    assert data["payload"]["title"] == "Ops"
    assert data["payload"]["include_chat_ids"] == [123]


def test_folder_edit_preserves_existing_peers_and_updates_flags(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[FakeInputPeer(123)], exclude=[FakeInputPeer(456)])]
            return True

        async def get_input_entity(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folder_edit_runner(_args(
        folder_id=2,
        title="Ops 2",
        emoticon="✅",
        include_chat=[789],
        groups=False,
        bots=True,
        idempotency_key="folder-edit-1",
    )))

    assert data["folder_id"] == 2
    assert data["edited"] is True
    update = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"][0]
    assert update.id == 2
    assert update.filter.title.text == "Ops 2"
    assert update.filter.emoticon == "✅"
    assert [peer.peer_id for peer in update.filter.include_peers] == [123, 789]
    assert [peer.peer_id for peer in update.filter.exclude_peers] == [456]
    assert update.filter.groups is False
    assert update.filter.bots is True


def test_folder_edit_requires_mutation():
    with pytest.raises(BadArgs, match="nothing to edit"):
        chats._folder_edit_mutations(_args(folder_id=2))


def test_folder_delete_rejects_default_folder():
    with pytest.raises(BadArgs, match="folder id 0 is reserved"):
        asyncio.run(chats._folder_delete_runner(_args(folder_id=0)))


def test_folder_delete_uses_none_filter_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return True

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_id=2, idempotency_key="folder-delete-1")

    first = asyncio.run(chats._folder_delete_runner(args))
    second = asyncio.run(chats._folder_delete_runner(args))

    assert first["deleted"] is True
    assert second["idempotent_replay"] is True
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.__class__.__name__ == "UpdateDialogFilterRequest"
    assert request.id == 2
    assert request.filter is None


def test_folder_add_chat_resolves_chat_and_replays_idempotency(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[])]
            return True

        async def get_input_entity(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_id=2, chat="@alpha_forum", idempotency_key="folder-add-1")

    first = asyncio.run(chats._folder_add_chat_runner(args))
    second = asyncio.run(chats._folder_add_chat_runner(args))

    assert first["chat"] == {"chat_id": 123, "title": "Alpha Forum"}
    assert first["added"] is True
    assert second["idempotent_replay"] is True
    updates = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"]
    assert len(updates) == 1
    assert [peer.peer_id for peer in updates[0].filter.include_peers] == [123]


def test_folder_remove_chat_warns_when_chat_is_excluded(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            if request.__class__.__name__ == "GetDialogFiltersRequest":
                return [_filter(folder_id=2, title="Ops", include=[], exclude=[FakeInputPeer(123)])]
            return True

        async def get_input_entity(self, chat_id):
            return FakeInputPeer(chat_id)

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    data = asyncio.run(chats._folder_remove_chat_runner(_args(
        folder_id=2,
        chat="@alpha_forum",
        idempotency_key="folder-remove-1",
    )))

    assert data["removed"] is False
    assert data["warnings"] == ["chat was present in exclude_peers, not include_peers"]
    update = [request for request in fake.requests if request.__class__.__name__ == "UpdateDialogFilterRequest"][0]
    assert update.filter.include_peers == []
    assert [peer.peer_id for peer in update.filter.exclude_peers] == [123]


def test_folders_reorder_uses_order_request_and_replays(monkeypatch, tmp_path):
    db = tmp_path / "telegram.sqlite"
    _seed_chat(db)
    monkeypatch.setattr(chats, "DB_PATH", db)

    class FakeClient:
        def __init__(self):
            self.requests = []

        async def start(self):
            pass

        async def __call__(self, request):
            self.requests.append(request)
            return True

        async def disconnect(self):
            pass

    fake = FakeClient()
    monkeypatch.setattr(chats, "make_client", lambda session_path: fake)
    args = _args(folder_ids=[2, 3, 4], idempotency_key="folders-reorder-1")

    first = asyncio.run(chats._folders_reorder_runner(args))
    second = asyncio.run(chats._folders_reorder_runner(args))

    assert first["order"] == [2, 3, 4]
    assert second["idempotent_replay"] is True
    assert len(fake.requests) == 1
    assert fake.requests[0].__class__.__name__ == "UpdateDialogFiltersOrderRequest"
    assert fake.requests[0].order == [2, 3, 4]
