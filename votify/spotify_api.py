from __future__ import annotations

import functools
import json
import re
import time
import typing
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import base62
import requests

from .utils import check_response


class SpotifyApi:
    SPOTIFY_HOME_PAGE_URL = "https://open.spotify.com/"
    CLIENT_VERSION = "1.2.46.25.g7f189073"
    LYRICS_API_URL = "https://spclient.wg.spotify.com/color-lyrics/v2/track/{track_id}"
    METADATA_API_URL = "https://api.spotify.com/v1/{type}/{track_id}"
    GID_METADATA_API_URL = "https://spclient.wg.spotify.com/metadata/4/{media_type}/{gid}?market=from_token"
    PLAYPLAY_LICENSE_API_URL = (
        "https://gew4-spclient.spotify.com/playplay/v1/key/{file_id}"
    )
    TRACK_CREDITS_API_URL = "https://spclient.wg.spotify.com/track-credits-view/v0/experimental/{track_id}/credits"
    STREAM_URLS_API_URL = (
        "https://gue1-spclient.spotify.com/storage-resolve/v2/files/audio/interactive/11/"
        "{file_id}?version=10000000&product=9&platform=39&alt=json"
    )
    EXTEND_TRACK_COLLECTION_WAIT_TIME = 0.5

    def __init__(
        self,
        cookies_path: Path | None = Path("./cookies.txt"),
    ):
        self.cookies_path = cookies_path
        self._set_session()

    def _set_session(self):
        self.session = requests.Session()
        if self.cookies_path:
            cookies = MozillaCookieJar(self.cookies_path)
            cookies.load(ignore_discard=True, ignore_expires=True)
            self.session.cookies.update(cookies)
        self.session.headers.update(
            {
                "accept": "application/json",
                "accept-language": "en-US",
                "content-type": "application/json",
                "origin": self.SPOTIFY_HOME_PAGE_URL,
                "priority": "u=1, i",
                "referer": self.SPOTIFY_HOME_PAGE_URL,
                "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "spotify-app-version": self.CLIENT_VERSION,
                "app-platform": "WebPlayer",
            }
        )
        self._set_session_auth()

    def _set_session_auth(self):
        home_page = self.get_home_page()
        self.session_info = json.loads(
            re.search(
                r'<script id="session" data-testid="session" type="application/json">(.+?)</script>',
                home_page,
            ).group(1)
        )
        self.config_info = json.loads(
            re.search(
                r'<script id="config" data-testid="config" type="application/json">(.+?)</script>',
                home_page,
            ).group(1)
        )
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.session_info['accessToken']}",
            }
        )

    def _refresh_session_auth(self):
        timestamp_session_expire = int(
            self.session_info["accessTokenExpirationTimestampMs"]
        )
        timestamp_now = time.time() * 1000
        if timestamp_now < timestamp_session_expire:
            return
        self._set_session_auth()

    def get_home_page(self) -> str:
        response = self.session.get(
            SpotifyApi.SPOTIFY_HOME_PAGE_URL,
        )
        check_response(response)
        return response.text

    @staticmethod
    def media_id_to_gid(media_id: str) -> str:
        return hex(base62.decode(media_id, base62.CHARSET_INVERTED))[2:].zfill(32)

    @staticmethod
    def gid_to_media_id(gid: str) -> str:
        return base62.encode(int(gid, 16), charset=base62.CHARSET_INVERTED).zfill(22)

    def get_gid_metadata(
        self,
        gid: str,
        media_type: str,
    ) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.GID_METADATA_API_URL.format(gid=gid, media_type=media_type)
        )
        check_response(response)
        return response.json()

    def get_lyrics(self, track_id: str) -> dict | None:
        self._refresh_session_auth()
        response = self.session.get(self.LYRICS_API_URL.format(track_id=track_id))
        if response.status_code == 404:
            return None
        check_response(response)
        return response.json()

    def get_track(self, track_id: str) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.METADATA_API_URL.format(type="tracks", track_id=track_id)
        )
        check_response(response)
        return response.json()

    def extend_track_collection(
        self,
        track_collection: dict,
        media_type: str,
    ) -> typing.Generator[dict, None, None]:
        next_url = track_collection[media_type]["next"]
        while next_url is not None:
            response = self.session.get(next_url)
            check_response(response)
            extended_collection = response.json()
            yield extended_collection
            next_url = extended_collection["next"]
            time.sleep(self.EXTEND_TRACK_COLLECTION_WAIT_TIME)

    @functools.lru_cache()
    def get_album(
        self,
        album_id: str,
        extend: bool = True,
    ) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.METADATA_API_URL.format(type="albums", track_id=album_id)
        )
        check_response(response)
        album = response.json()
        if extend:
            album["tracks"]["items"].extend(
                [
                    item
                    for extended_collection in self.extend_track_collection(
                        album,
                        "tracks",
                    )
                    for item in extended_collection["items"]
                ]
            )
        return album

    def get_playlist(
        self,
        playlist_id: str,
        extend: bool = True,
    ) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.METADATA_API_URL.format(type="playlists", track_id=playlist_id)
        )
        check_response(response)
        playlist = response.json()
        if extend:
            playlist["tracks"]["items"].extend(
                [
                    item
                    for extended_collection in self.extend_track_collection(
                        playlist,
                        "tracks",
                    )
                    for item in extended_collection["items"]
                ]
            )
        return playlist

    def get_track_credits(self, track_id: str) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.TRACK_CREDITS_API_URL.format(track_id=track_id)
        )
        check_response(response)
        return response.json()

    def get_episode(self, episode_id: str) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.METADATA_API_URL.format(type="episodes", track_id=episode_id)
        )
        check_response(response)
        return response.json()

    def get_show(self, show_id: str, extend: bool = True) -> dict:
        self._refresh_session_auth()
        response = self.session.get(
            self.METADATA_API_URL.format(type="shows", track_id=show_id)
        )
        check_response(response)
        show = response.json()
        if extend:
            show["episodes"]["items"].extend(
                [
                    item
                    for extended_collection in self.extend_track_collection(
                        show,
                        "episodes",
                    )
                    for item in extended_collection["items"]
                ]
            )
        return show

    def get_playplay_license(self, file_id: str, challenge: bytes) -> bytes:
        self._refresh_session_auth()
        response = self.session.post(
            self.PLAYPLAY_LICENSE_API_URL.format(file_id=file_id),
            challenge,
        )
        check_response(response)
        return response.content

    def get_stream_urls(self, file_id: str) -> str:
        self._refresh_session_auth()
        response = self.session.get(self.STREAM_URLS_API_URL.format(file_id=file_id))
        check_response(response)
        return response.json()