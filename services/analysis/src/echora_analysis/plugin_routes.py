"""Versioned Echora plugin API returning Navidrome provider response envelopes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .navidrome_integration import authenticate
from . import plugin_ranking as ranking
from .plugin_lyrics import load_lyrics


class Song(BaseModel):
    id: str = Field(min_length=1, max_length=256)


class SimilarRequest(BaseModel):
    song: Song
    count: int = Field(default=20, ge=1, le=500)


class PathRequest(BaseModel):
    startSong: Song
    endSong: Song
    count: int = Field(default=25, ge=2, le=500)


class ArtistRequest(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    count: int = Field(default=20, ge=1, le=500)
    limit: int = Field(default=10, ge=1, le=100)


class LyricsRequest(BaseModel):
    track: Song


router = APIRouter(prefix="/integrations/navidrome/v1", tags=["navidrome-plugin"])


@router.post("/similar-tracks")
def similar(body: SimilarRequest, principal=Depends(authenticate)):
    return ranking.similar_tracks(
        ranking.load_corpus(principal), body.song.id, body.count, principal["profile"]
    )


@router.post("/sonic-path")
def path(body: PathRequest, principal=Depends(authenticate)):
    return ranking.sonic_path(
        ranking.load_corpus(principal),
        body.startSong.id,
        body.endSong.id,
        body.count,
        principal["profile"],
    )


@router.post("/similar-artists")
def artists(body: ArtistRequest, principal=Depends(authenticate)):
    return ranking.similar_artists(
        ranking.load_corpus(principal), body.id, body.limit, principal["profile"]
    )


@router.post("/artist-radio")
def radio(body: ArtistRequest, principal=Depends(authenticate)):
    return ranking.artist_radio(
        ranking.load_corpus(principal), body.id, body.count, principal["profile"]
    )


@router.post("/lyrics")
def lyrics(body: LyricsRequest, principal=Depends(authenticate)):
    return load_lyrics(principal, body.track.id)
