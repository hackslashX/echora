from echora_analysis.navidrome import NavidromeClient


def test_replace_playlist_updates_existing_id_without_creating_or_deleting() -> None:
    client = object.__new__(NavidromeClient)
    calls = []

    def request(method: str, **params: object):
        calls.append((method, params))
        return {"playlist": {"id": "existing"}}

    client._request = request

    result = client.replace_playlist("My list", ["one", "two"], "existing")

    assert result == "existing"
    assert calls == [("createPlaylist", {"songId": ["one", "two"], "playlistId": "existing"})]


def test_replace_playlist_creates_by_name_when_no_id_exists() -> None:
    client = object.__new__(NavidromeClient)
    calls = []

    def request(method: str, **params: object):
        calls.append((method, params))
        return {"playlist": {"id": "new"}}

    client._request = request

    assert client.replace_playlist("My list", ["one"], None) == "new"
    assert calls == [("createPlaylist", {"songId": ["one"], "name": "My list"})]


def test_catalog_exceeds_old_limit_and_probes_short_pages():
    client = object.__new__(NavidromeClient)
    def request(method, **params):
        offset = params['songOffset']
        return {'searchResult3': {'song': [{'id': str(i)} for i in range(offset, min(offset + 211, 20003))]}}
    client._request = request
    assert len(client.all_tracks()) == 20003


def test_catalog_rejects_repetition_and_incomplete_responses():
    import pytest
    client = object.__new__(NavidromeClient)
    client._request = lambda *a, **k: {'searchResult3': {'song': [{'id': 'same'}]}}
    with pytest.raises(RuntimeError, match='Repeating'):
        client.all_tracks()
    client._request = lambda *a, **k: {}
    with pytest.raises(RuntimeError, match='Incomplete'):
        client.all_tracks()


def test_batch_audio_cache_reuses_bytes_and_cleans_up():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from echora_analysis.navidrome import batch_audio_cache, _batch_state
    client = object.__new__(NavidromeClient)
    client.base_url, client.username = 'https://music/', 'user'
    client._auth = lambda: {}
    client.client = SimpleNamespace(get=Mock(return_value=SimpleNamespace(content=b'audio', raise_for_status=lambda: None)))
    class Cancelled(BaseException):
        pass
    import pytest
    with pytest.raises(Cancelled):
        with batch_audio_cache():
            directory = _batch_state.get()['directory']
            assert client.audio_bytes('one') == client.audio_bytes('one') == b'audio'
            assert client.client.get.call_count == 1
            raise Cancelled()
    assert not directory.exists()
    assert _batch_state.get() is None
