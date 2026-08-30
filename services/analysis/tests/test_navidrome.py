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
