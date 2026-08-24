from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import secrets
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class NavidromeTrack:
    id: str
    title: str
    artist: str | None
    album: str | None
    duration: float
    year: int | None
    genre: str | None
    suffix: str | None
    path: str | None
    raw: dict[str, object]


class NavidromeClient:
    """Small Subsonic client. Credentials are only sent from the analysis service."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.client = httpx.Client(timeout=httpx.Timeout(30, read=300), follow_redirects=True)

    def _auth(self) -> dict[str, str]:
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode(), usedforsecurity=False).hexdigest()
        return {"u": self.username, "t": token, "s": salt, "v": "1.16.1", "c": "echora", "f": "json"}

    def _endpoint(self, method: str) -> str:
        return urljoin(self.base_url, f"rest/{method}.view")

    def _request(self, method: str, **params: object) -> dict[str, object]:
        response = self.client.get(self._endpoint(method), params={**self._auth(), **params})
        response.raise_for_status()
        payload = response.json()["subsonic-response"]
        if payload.get("status") != "ok":
            raise RuntimeError(f"Navidrome error: {payload.get('error', {}).get('message', 'unknown')}")
        return payload

    @staticmethod
    def _track(song: dict[str, object]) -> NavidromeTrack:
        return NavidromeTrack(
            id=str(song["id"]),
            title=str(song.get("title") or "Unknown title"),
            artist=song.get("artist"),
            album=song.get("album"),
            duration=float(song.get("duration") or 0),
            year=int(song["year"]) if song.get("year") else None,
            genre=song.get("genre"),
            suffix=song.get("suffix"),
            path=song.get("path"),
            raw=song,
        )

    def ping(self) -> str:
        payload = self._request("ping")
        return str(payload.get("serverVersion") or payload.get("version") or "Subsonic")

    def random_tracks(self, size: int = 100) -> list[NavidromeTrack]:
        payload = self._request("getRandomSongs", size=size)
        songs = payload.get("randomSongs", {}).get("song", [])
        return [self._track(song) for song in songs]

    def all_tracks(self, page_size: int = 500, maximum: int = 20000) -> list[NavidromeTrack]:
        tracks: list[NavidromeTrack] = []
        offset = 0
        while len(tracks) < maximum:
            payload = self._request(
                "search3", query="", songCount=min(page_size, maximum - len(tracks)), songOffset=offset,
                artistCount=0, albumCount=0,
            )
            songs = payload.get("searchResult3", {}).get("song", [])
            tracks.extend(self._track(song) for song in songs)
            if len(songs) < page_size:
                break
            offset += len(songs)
        return tracks

    def tracks(self, song_ids: list[str]) -> list[NavidromeTrack]:
        tracks = []
        for song_id in song_ids:
            payload = self._request("getSong", id=song_id)
            tracks.append(self._track(payload["song"]))
        return tracks

    def lyrics(self, song_id: str) -> dict[str, object]:
        try:
            payload = self._request("getLyricsBySongId", id=song_id)
            entries = payload.get("lyricsList", {}).get("structuredLyrics", [])
            if entries:
                entry = entries[0]
                lines = entry.get("line", [])
                text = "\n".join(str(line.get("value") or "") for line in lines).strip()
                return {
                    "status": "available" if text else "missing", "text": text or None,
                    "language": entry.get("lang"), "synced": bool(entry.get("synced")),
                    "lines": [{"start_ms": line.get("start"), "text": line.get("value") or ""} for line in lines],
                    "source": "getLyricsBySongId",
                }
        except Exception:
            pass
        try:
            payload = self._request("getLyrics", songId=song_id)
            entry = payload.get("lyrics") or {}
            text = str(entry.get("value") or "").strip()
            return {"status": "available" if text else "missing", "text": text or None,
                    "language": None, "synced": False, "lines": [], "source": "getLyrics"}
        except Exception:
            return {"status": "unavailable", "text": None, "language": None, "synced": False,
                    "lines": [], "source": "navidrome"}

    def playlists(self) -> list[dict[str, object]]:
        payload = self._request("getPlaylists")
        return list(payload.get("playlists", {}).get("playlist", []))

    def replace_playlist(self, name: str, song_ids: list[str], playlist_id: str | None = None) -> str:
        payload = self._request("createPlaylist", name=name, songId=song_ids)
        playlist = payload.get("playlist") or {}
        if not playlist.get("id"):
            raise RuntimeError("Navidrome did not return the created playlist ID")
        created_id = str(playlist["id"])
        if playlist_id and playlist_id != created_id:
            self._request("deletePlaylist", id=playlist_id)
        return created_id

    def delete_playlist(self, playlist_id: str) -> None:
        self._request("deletePlaylist", id=playlist_id)

    def catalog(self) -> dict[str, list[dict[str, object]]]:

        album_payload = self._request("getAlbumList2", type="alphabeticalByName", size=500)
        artist_payload = self._request("getArtists")
        albums = album_payload.get("albumList2", {}).get("album", [])
        indexes = artist_payload.get("artists", {}).get("index", [])
        artists = [artist for index in indexes for artist in index.get("artist", [])]
        return {"albums": albums, "artists": artists}

    def cover_art(self, cover_id: str, size: int = 160) -> tuple[bytes, str]:
        response = self.client.get(
            self._endpoint("getCoverArt"),
            params={**self._auth(), "id": cover_id, "size": size},
        )
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "image/jpeg")

    def transcode_chunks(self, song_id: str, max_bit_rate: int = 320, range_header: str | None = None) -> Iterator[bytes]:
        headers = {"Range": range_header} if range_header else {}
        with self.client.stream(
            "GET",
            self._endpoint("stream"),
            params={**self._auth(), "id": song_id, "format": "mp3", "maxBitRate": max_bit_rate, "estimateContentLength": "true"},
            headers=headers,
        ) as response:
            response.raise_for_status()
            yield from response.iter_bytes(64 * 1024)

    def open_transcode_stream(self, song_id: str, max_bit_rate: int = 320, range_header: str | None = None) -> httpx.Response:
        request = self.client.build_request(
            "GET",
            self._endpoint("stream"),
            params={**self._auth(), "id": song_id, "format": "mp3", "maxBitRate": max_bit_rate, "estimateContentLength": "true"},
            headers={"Range": range_header} if range_header else {},
        )
        response = self.client.send(request, stream=True)
        response.raise_for_status()
        if "application/json" in response.headers.get("content-type", ""):
            try:
                response.read()
                payload = response.json().get("subsonic-response", {})
                message = payload.get("error", {}).get("message", "Navidrome returned JSON instead of audio")
            except Exception:
                message = "Navidrome returned JSON instead of audio"
            response.close()
            raise RuntimeError(str(message))
        return response

    def transcode_range(self, song_id: str, range_header: str, max_bit_rate: int = 320) -> tuple[bytes, dict[str, str], int]:
        response = self.client.get(
            self._endpoint("stream"),
            params={**self._auth(), "id": song_id, "format": "mp3", "maxBitRate": max_bit_rate, "estimateContentLength": "true"},
            headers={"Range": range_header},
        )
        response.raise_for_status()
        headers = {key: value for key, value in response.headers.items() if key.lower() in {"content-length", "content-range", "accept-ranges"}}
        return response.content, headers, response.status_code

    def transcode(self, song_id: str, max_bit_rate: int = 320) -> tuple[bytes, str]:
        response = self.client.get(
            self._endpoint("stream"),
            params={**self._auth(), "id": song_id, "format": "mp3", "maxBitRate": max_bit_rate, "estimateContentLength": "true"},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "audio/mpeg")
        if "application/json" in content_type:
            try:
                payload = response.json().get("subsonic-response", {})
                message = payload.get("error", {}).get("message", "Navidrome returned JSON instead of audio")
            except Exception:
                message = "Navidrome returned JSON instead of audio"
            raise RuntimeError(str(message))
        return response.content, content_type

    def audio_bytes(self, song_id: str) -> bytes:
        response = self.client.get(
            self._endpoint("stream"),
            params={**self._auth(), "id": song_id, "format": "raw", "estimateContentLength": "true"},
        )
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "NavidromeClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
