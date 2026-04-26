# -*- coding: utf-8 -*-
import time
import requests
import xbmc
import xbmcgui
import xbmcaddon
import webbrowser

from resources.utils import giptv

ADDON = xbmcaddon.Addon()

TRAKT_API = "https://api.trakt.tv"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

TRAKT_CLIENT_ID = "f72fb38e17133eb0b837b562fd0bc0e361e734c1b20a14bd5768ec2f745aa62b"
TRAKT_CLIENT_SECRET = "741888a1131f4c570d83f191939888b5224a5f9a4bdfd872201ffadbf1673238"

_PLAYBACK_CACHE_TTL = 20.0
_PLAYBACK_CACHE = {
    "movies": {"time": 0.0, "items": None},
    "episodes": {"time": 0.0, "items": None},
}

_SHOW_PROGRESS_CACHE_TTL = 60.0
_SHOW_PROGRESS_CACHE = {}

_TV_PROGRESS_MAPS_CACHE_TTL = 30.0
_TV_PROGRESS_MAPS_CACHE = {
    "time": 0.0,
    "data": None,
}


def _get_setting(key, default=""):
    try:
        value = ADDON.getSetting(key)
        return value if value != "" else default
    except Exception:
        return default


def _set_setting(key, value):
    try:
        ADDON.setSetting(key, str(value))
    except Exception:
        pass


def _safe_int(value):
    try:
        if value in (None, "", "None", "null"):
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_float(value):
    try:
        if value in (None, "", "None", "null"):
            return None
        return float(value)
    except Exception:
        return None


def _client_id():
    return TRAKT_CLIENT_ID


def _client_secret():
    return TRAKT_CLIENT_SECRET


def _headers(with_auth=False):
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": _client_id(),
    }

    if with_auth:
        token = _get_setting("trakt_access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

    return headers


def _normalize_progress(progress):
    progress = _safe_float(progress)
    if progress is None:
        return None
    return max(0.0, min(100.0, progress))


def _playback_type_value(stream_type):
    if stream_type in ("vod", "movies"):
        return "movies"
    if stream_type in ("series", "episodes"):
        return "episodes"
    return None


def _invalidate_playback_cache(playback_type=None):
    global _PLAYBACK_CACHE

    if playback_type in ("movies", "episodes"):
        _PLAYBACK_CACHE[playback_type]["time"] = 0.0
        _PLAYBACK_CACHE[playback_type]["items"] = None
        return

    for key in ("movies", "episodes"):
        _PLAYBACK_CACHE[key]["time"] = 0.0
        _PLAYBACK_CACHE[key]["items"] = None


def _get_cached_playback(playback_type):
    cache = _PLAYBACK_CACHE.get(playback_type) or {}
    items = cache.get("items")

    try:
        ts = float(cache.get("time", 0) or 0)
    except Exception:
        ts = 0.0

    if items is None:
        return None

    if (time.time() - ts) > float(_PLAYBACK_CACHE_TTL):
        return None

    return items


def _set_cached_playback(playback_type, items):
    _PLAYBACK_CACHE[playback_type] = {
        "time": float(time.time()),
        "items": items or [],
    }


def _get_cached_show_progress(tmdb_id):
    key = str(tmdb_id or "")
    cached = _SHOW_PROGRESS_CACHE.get(key)
    if not cached:
        return None

    try:
        ts = float(cached.get("time", 0) or 0)
    except Exception:
        ts = 0.0

    if (time.time() - ts) > float(_SHOW_PROGRESS_CACHE_TTL):
        return None

    return cached.get("data")


def _set_cached_show_progress(tmdb_id, data):
    _SHOW_PROGRESS_CACHE[str(tmdb_id or "")] = {
        "time": float(time.time()),
        "data": data,
    }


def _invalidate_show_progress_cache(tmdb_id=None):
    if tmdb_id is None:
        _SHOW_PROGRESS_CACHE.clear()
        return
    _SHOW_PROGRESS_CACHE.pop(str(tmdb_id), None)


def _get_cached_tv_progress_maps():
    cached = _TV_PROGRESS_MAPS_CACHE
    data = cached.get("data")
    if data is None:
        return None

    try:
        ts = float(cached.get("time", 0) or 0)
    except Exception:
        ts = 0.0

    if (time.time() - ts) > float(_TV_PROGRESS_MAPS_CACHE_TTL):
        return None

    return data


def _set_cached_tv_progress_maps(data):
    _TV_PROGRESS_MAPS_CACHE["time"] = float(time.time())
    _TV_PROGRESS_MAPS_CACHE["data"] = data or {}


def _invalidate_tv_progress_maps_cache():
    _TV_PROGRESS_MAPS_CACHE["time"] = 0.0
    _TV_PROGRESS_MAPS_CACHE["data"] = None


def _movie_ids_payload(tmdb_id):
    tmdb_id = _safe_int(tmdb_id)
    if tmdb_id is None:
        return None
    return {"ids": {"tmdb": tmdb_id}}


def _show_ids_payload(tmdb_id):
    tmdb_id = _safe_int(tmdb_id)
    if tmdb_id is None:
        return None
    return {"ids": {"tmdb": tmdb_id}}


def _season_show_payload(tmdb_id, season):
    tmdb_id = _safe_int(tmdb_id)
    season = _safe_int(season)

    if tmdb_id is None or season is None:
        return None

    return {
        "ids": {"tmdb": tmdb_id},
        "seasons": [
            {
                "number": season,
            }
        ],
    }


def _episode_show_payload(tmdb_id, season, episode):
    tmdb_id = _safe_int(tmdb_id)
    season = _safe_int(season)
    episode = _safe_int(episode)

    if tmdb_id is None or season is None or episode is None:
        return None

    return {
        "ids": {"tmdb": tmdb_id},
        "seasons": [
            {
                "number": season,
                "episodes": [{"number": episode}],
            }
        ],
    }


def _movie_scrobble_payload(tmdb_id, progress):
    movie_ids = _movie_ids_payload(tmdb_id)
    progress = _normalize_progress(progress)

    if movie_ids is None or progress is None:
        return None

    return {
        "movie": movie_ids,
        "progress": progress,
    }


def _episode_scrobble_payload(tmdb_id, season, episode, progress):
    tmdb_id = _safe_int(tmdb_id)
    season = _safe_int(season)
    episode = _safe_int(episode)
    progress = _normalize_progress(progress)

    if tmdb_id is None or season is None or episode is None or progress is None:
        return None

    return {
        "show": {"ids": {"tmdb": tmdb_id}},
        "episode": {
            "season": season,
            "number": episode,
        },
        "progress": progress,
    }


def trakt_get_tv_episode_maps(force_refresh=False):
    return {
        "watched_episode_keys_by_show": trakt_get_watched_episode_keys_by_show(
            force_refresh=force_refresh
        ),
        "episode_resume_map_by_show": trakt_get_episode_resume_map_by_show(
            force_refresh=force_refresh
        ),
    }


def trakt_is_configured():
    return bool(_client_id() and _client_secret())


def trakt_is_authenticated():
    token = _get_setting("trakt_access_token")
    refresh = _get_setting("trakt_refresh_token")
    return bool(token and refresh)


def trakt_get_username():
    return _get_setting("trakt_username")


def trakt_refresh_token():
    if not trakt_is_configured():
        return False

    refresh_token = _get_setting("trakt_refresh_token")
    if not refresh_token:
        return False

    payload = {
        "refresh_token": refresh_token,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "redirect_uri": REDIRECT_URI,
        "grant_type": "refresh_token",
    }

    try:
        resp = requests.post(
            f"{TRAKT_API}/oauth/token",
            json=payload,
            headers=_headers(with_auth=False),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return trakt_store_token(data)
    except Exception as e:
        giptv.log(f"Trakt refresh failed: {e}", xbmc.LOGERROR)
        return False


def trakt_ensure_valid_token():
    if not trakt_is_authenticated():
        return False

    try:
        expires_at = int(_get_setting("trakt_expires_at", "0"))
    except Exception:
        expires_at = 0

    now = int(time.time())
    if now < max(0, expires_at - 300):
        return True

    return trakt_refresh_token()


def trakt_request(path, method="GET", data=None, with_auth=True):
    if with_auth and not trakt_ensure_valid_token():
        return None

    resp = None
    try:
        headers = _headers(with_auth=with_auth)
        url = f"{TRAKT_API}/{path}"

        if method == "POST":
            resp = requests.post(url, json=data, headers=headers, timeout=20)
        elif method == "DELETE":
            resp = requests.delete(url, json=data, headers=headers, timeout=20)
        else:
            resp = requests.get(url, headers=headers, timeout=20)

        resp.raise_for_status()

        if "application/json" in resp.headers.get("Content-Type", ""):
            return resp.json()

        return {}
    except Exception as e:
        body = ""
        try:
            body = resp.text if resp is not None else ""
        except Exception:
            pass

        giptv.log(
            f"Trakt request failed: path={path} error={e} body={body}",
            xbmc.LOGERROR,
        )
        return None


def trakt_get_device_code():
    if not trakt_is_configured():
        giptv.notification(
            ADDON.getAddonInfo("name"), "Trakt credentials missing", icon="ERROR"
        )
        return None

    payload = {"client_id": _client_id()}

    try:
        resp = requests.post(
            f"{TRAKT_API}/oauth/device/code",
            json=payload,
            headers=_headers(with_auth=False),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        giptv.log(f"Trakt device code failed: {e}", xbmc.LOGERROR)
        giptv.notification(
            ADDON.getAddonInfo("name"), "Failed to start Trakt auth", icon="ERROR"
        )
        return None


def _build_verification_url(device_code_data):
    verification_url = device_code_data.get(
        "verification_url", "https://trakt.tv/activate"
    )
    verification_complete = device_code_data.get("verification_url_complete")
    user_code = device_code_data.get("user_code", "")

    if verification_complete:
        return verification_complete

    if user_code:
        return f"{verification_url}?code={user_code}"

    return verification_url


def _show_trakt_auth_intro(device_code_data):
    verification_url = device_code_data.get(
        "verification_url", "https://trakt.tv/activate"
    )
    user_code = device_code_data.get("user_code", "")
    auth_url = _build_verification_url(device_code_data)

    choice = xbmcgui.Dialog().yesnocustom(
        "Trakt Authorization",
        f"Go to: {verification_url}[CR]Enter code: {user_code}[CR][CR]Open browser now?",
        yeslabel="Continue",
        nolabel="Open browser",
        customlabel="Cancel",
    )

    if choice == 0:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass


def trakt_poll_for_token(device_code_data):
    if not device_code_data:
        return None

    payload = {
        "code": device_code_data["device_code"],
        "client_id": _client_id(),
        "client_secret": _client_secret(),
    }

    interval = int(device_code_data.get("interval", 5))
    expires_in = int(device_code_data.get("expires_in", 600))
    start = time.time()

    verification_url = device_code_data.get(
        "verification_url", "https://trakt.tv/activate"
    )
    user_code = device_code_data.get("user_code", "")
    auth_url = _build_verification_url(device_code_data)

    _show_trakt_auth_intro(device_code_data)

    dialog = xbmcgui.DialogProgress()
    dialog.create(
        "Trakt Authorization",
        f"Go to: {verification_url}[CR]Enter code: {user_code}[CR]{auth_url}",
    )

    try:
        while not dialog.iscanceled():
            elapsed = int(time.time() - start)
            if elapsed >= expires_in:
                break

            remaining = max(0, expires_in - elapsed)
            percent = int((elapsed / float(expires_in)) * 100)

            dialog.update(
                percent,
                f"Go to: {verification_url}[CR]Enter code: {user_code}[CR]"
                f"Time remaining: {remaining}s",
            )

            try:
                resp = requests.post(
                    f"{TRAKT_API}/oauth/device/token",
                    json=payload,
                    headers=_headers(with_auth=False),
                    timeout=20,
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code in (400, 404, 409, 410, 418, 429):
                    xbmc.sleep(interval * 1000)
                    continue

                xbmc.sleep(interval * 1000)
            except Exception:
                xbmc.sleep(interval * 1000)
    finally:
        dialog.close()

    return None


def trakt_store_token(token_data):
    if not token_data:
        return False

    try:
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = int(token_data.get("expires_in", 0))
        created_at = int(time.time())

        _set_setting("trakt_access_token", access_token)
        _set_setting("trakt_refresh_token", refresh_token)
        _set_setting("trakt_expires_at", str(created_at + expires_in))
        return True
    except Exception:
        return False


def trakt_get_me():
    if not trakt_ensure_valid_token():
        return None

    try:
        resp = requests.get(
            f"{TRAKT_API}/users/me",
            headers=_headers(with_auth=True),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        giptv.log(f"Trakt users/me failed: {e}", xbmc.LOGERROR)
        return None


def trakt_authenticate():
    device_code_data = trakt_get_device_code()
    if not device_code_data:
        return False

    token_data = trakt_poll_for_token(device_code_data)
    if not token_data:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "Trakt authorization cancelled or expired",
            icon="ERROR",
        )
        return False

    if not trakt_store_token(token_data):
        giptv.notification(
            ADDON.getAddonInfo("name"), "Failed to save Trakt token", icon="ERROR"
        )
        return False

    me = trakt_get_me()
    if me and me.get("username"):
        _set_setting("trakt_username", me["username"])

    giptv.notification(ADDON.getAddonInfo("name"), "Trakt authorized", icon="INFO")
    return True


def trakt_revoke_auth():
    access_token = _get_setting("trakt_access_token")
    if access_token and trakt_is_configured():
        payload = {
            "token": access_token,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
        }
        try:
            requests.post(
                f"{TRAKT_API}/oauth/revoke",
                json=payload,
                headers=_headers(with_auth=False),
                timeout=15,
            )
        except Exception:
            pass

    _set_setting("trakt_access_token", "")
    _set_setting("trakt_refresh_token", "")
    _set_setting("trakt_expires_at", "0")
    _set_setting("trakt_username", "")

    _invalidate_playback_cache()
    _invalidate_show_progress_cache()
    _invalidate_tv_progress_maps_cache()

    giptv.notification(
        ADDON.getAddonInfo("name"), "Trakt authorization removed", icon="INFO"
    )
    return True


def trakt_get_watched_movies():
    result = trakt_request("sync/watched/movies", method="GET", with_auth=True)
    if isinstance(result, list):
        return result
    return []


def trakt_get_watched_movie_ids():
    items = trakt_get_watched_movies()
    ids = set()

    for item in items:
        try:
            movie = item.get("movie") or {}
            movie_ids = movie.get("ids") or {}
            tmdb_id = _safe_int(movie_ids.get("tmdb"))
            if tmdb_id is not None:
                ids.add(str(tmdb_id))
        except Exception:
            pass

    return ids


def trakt_get_watched_shows():
    result = trakt_request("sync/watched/shows", method="GET", with_auth=True)
    if isinstance(result, list):
        return result
    return []


def trakt_get_show_watched_progress(tmdb_id, force_refresh=False):
    tmdb_id = _safe_int(tmdb_id)
    if tmdb_id is None:
        return None

    cache_key = str(tmdb_id)

    if not force_refresh:
        cached = _get_cached_show_progress(cache_key)
        if cached is not None:
            return cached

    result = trakt_request(
        f"shows/tmdb:{tmdb_id}/progress/watched?hidden=false&specials=false&count_specials=false",
        method="GET",
        with_auth=True,
    )

    if isinstance(result, dict):
        _set_cached_show_progress(cache_key, result)
        return result

    return None


def trakt_get_show_watched_episode_keys(tmdb_id):
    data = trakt_get_show_watched_progress(tmdb_id)
    watched = set()

    if not data:
        return watched

    for season in data.get("seasons", []):
        season_num = season.get("number")
        for episode in season.get("episodes", []):
            if episode.get("completed"):
                ep_num = episode.get("number")
                if season_num is not None and ep_num is not None:
                    watched.add((str(season_num), str(ep_num)))

    return watched


def trakt_get_playback(stream_type, force_refresh=False):
    playback_type = _playback_type_value(stream_type)
    if not playback_type:
        return []

    if not force_refresh:
        cached = _get_cached_playback(playback_type)
        if cached is not None:
            return cached

    result = trakt_request(
        f"sync/playback/{playback_type}",
        method="GET",
        with_auth=True,
    )

    if isinstance(result, list):
        _set_cached_playback(playback_type, result)
        return result

    return []


def trakt_get_movie_playback(tmdb_id):
    tmdb_id = _safe_int(tmdb_id)
    if tmdb_id is None:
        return None

    items = trakt_get_playback("vod")
    for item in items:
        movie = item.get("movie") or {}
        ids = movie.get("ids") or {}
        found_id = _safe_int(ids.get("tmdb"))
        if found_id == tmdb_id:
            return item

    return None


def trakt_get_episode_playback(tmdb_id, season, episode):
    tmdb_id = _safe_int(tmdb_id)
    season = _safe_int(season)
    episode = _safe_int(episode)

    if tmdb_id is None or season is None or episode is None:
        return None

    items = trakt_get_playback("series")
    for item in items:
        show = item.get("show") or {}
        show_ids = show.get("ids") or {}
        ep = item.get("episode") or {}

        found_tmdb = _safe_int(show_ids.get("tmdb"))
        found_season = _safe_int(ep.get("season"))
        found_episode = _safe_int(ep.get("number"))

        if (
            found_tmdb == tmdb_id
            and found_season == season
            and found_episode == episode
        ):
            return item

    return None


def trakt_get_movie_resume(tmdb_id):
    item = trakt_get_movie_playback(tmdb_id)
    if not item:
        return None

    progress = _safe_float(item.get("progress"))
    if progress is None or progress < 0.1 or progress >= 95.0:
        return None

    runtime = _safe_int((item.get("movie") or {}).get("runtime"))
    resume_seconds = 0
    if runtime and runtime > 0:
        resume_seconds = int((progress / 100.0) * runtime * 60)

    return {
        "progress": progress,
        "resume_seconds": resume_seconds,
        "playback_id": item.get("id"),
    }


def trakt_get_episode_resume(tmdb_id, season, episode):
    item = trakt_get_episode_playback(tmdb_id, season, episode)
    if not item:
        return None

    progress = _safe_float(item.get("progress"))
    if progress is None or progress < 0.1 or progress >= 95.0:
        return None

    runtime = _safe_int((item.get("episode") or {}).get("runtime"))
    resume_seconds = 0
    if runtime and runtime > 0:
        resume_seconds = int((progress / 100.0) * runtime * 60)

    return {
        "progress": progress,
        "resume_seconds": resume_seconds,
        "playback_id": item.get("id"),
    }


def trakt_get_movie_resume_map(force_refresh=False):
    items = trakt_get_playback("vod", force_refresh=force_refresh)
    out = {}

    for item in items:
        try:
            movie = item.get("movie") or {}
            ids = movie.get("ids") or {}
            tmdb_id = _safe_int(ids.get("tmdb"))
            progress = _safe_float(item.get("progress"))

            if tmdb_id is None or progress is None:
                continue
            if progress < 0.1 or progress >= 95.0:
                continue

            runtime = _safe_int(movie.get("runtime"))
            resume_seconds = 0
            if runtime and runtime > 0:
                resume_seconds = int((progress / 100.0) * runtime * 60)

            out[str(tmdb_id)] = {
                "progress": progress,
                "resume_seconds": resume_seconds,
                "playback_id": item.get("id"),
            }
        except Exception:
            pass

    return out


def trakt_get_episode_resume_map(tmdb_id, force_refresh=False):
    tmdb_id = _safe_int(tmdb_id)
    if tmdb_id is None:
        return {}

    items = trakt_get_playback("series", force_refresh=force_refresh)
    out = {}

    for item in items:
        try:
            show = item.get("show") or {}
            show_ids = show.get("ids") or {}
            found_tmdb = _safe_int(show_ids.get("tmdb"))
            if found_tmdb != tmdb_id:
                continue

            episode = item.get("episode") or {}
            season = _safe_int(episode.get("season"))
            ep_num = _safe_int(episode.get("number"))
            progress = _safe_float(item.get("progress"))

            if season is None or ep_num is None or progress is None:
                continue
            if progress < 0.1 or progress >= 95.0:
                continue

            runtime = _safe_int(episode.get("runtime"))
            resume_seconds = 0
            if runtime and runtime > 0:
                resume_seconds = int((progress / 100.0) * runtime * 60)

            out[(str(season), str(ep_num))] = {
                "progress": progress,
                "resume_seconds": resume_seconds,
                "playback_id": item.get("id"),
            }
        except Exception:
            pass

    return out


def trakt_get_watched_episode_keys_by_show(force_refresh=False):
    watched_items = trakt_get_watched_shows()
    out = {}

    for item in watched_items or []:
        try:
            show = item.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = _safe_int(ids.get("tmdb"))
            if tmdb_id is None:
                continue

            tmdb_key = str(tmdb_id)
            watched = out.setdefault(tmdb_key, set())

            for season in item.get("seasons") or []:
                try:
                    season_num = _safe_int(season.get("number"))
                    if season_num is None or season_num < 0:
                        continue

                    for ep in season.get("episodes") or []:
                        ep_num = _safe_int(ep.get("number"))
                        if ep_num is None or ep_num <= 0:
                            continue
                        watched.add((str(season_num), str(ep_num)))
                except Exception:
                    pass
        except Exception:
            pass

    return out


def trakt_get_episode_resume_map_by_show(force_refresh=False):
    items = trakt_get_playback("series", force_refresh=force_refresh)
    out = {}

    for item in items or []:
        try:
            show = item.get("show") or {}
            show_ids = show.get("ids") or {}
            tmdb_id = _safe_int(show_ids.get("tmdb"))
            if tmdb_id is None:
                continue

            episode = item.get("episode") or {}
            season = _safe_int(episode.get("season"))
            ep_num = _safe_int(episode.get("number"))
            progress = _safe_float(item.get("progress"))

            if season is None or ep_num is None or progress is None:
                continue
            if progress < 0.1 or progress >= 95.0:
                continue

            runtime = _safe_int(episode.get("runtime"))
            resume_seconds = 0
            if runtime and runtime > 0:
                resume_seconds = int((progress / 100.0) * runtime * 60)

            out.setdefault(str(tmdb_id), {})[(str(season), str(ep_num))] = {
                "progress": progress,
                "resume_seconds": resume_seconds,
                "playback_id": item.get("id"),
            }
        except Exception:
            pass

    return out


def trakt_get_tv_progress_maps(force_refresh=False):
    if not force_refresh:
        cached = _get_cached_tv_progress_maps()
        if cached is not None:
            return cached

    watched_items = trakt_get_watched_shows()
    playback_items = trakt_get_playback("series", force_refresh=force_refresh)

    show_summary_map = {}
    season_summary_map = {}
    watched_episode_keys_by_show = {}
    episode_resume_map_by_show = {}

    # ------------------------------------------------------------------
    # Build watched episode maps from sync/watched/shows
    # ------------------------------------------------------------------
    for item in watched_items or []:
        try:
            show = item.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = _safe_int(ids.get("tmdb"))
            if tmdb_id is None:
                continue

            tmdb_key = str(tmdb_id)
            seasons = item.get("seasons") or []

            watched_episode_keys = set()
            per_season = {}

            for season in seasons:
                try:
                    season_num = _safe_int(season.get("number"))
                    if season_num is None or season_num < 0:
                        continue

                    season_key = str(season_num)
                    episodes = season.get("episodes") or []

                    completed_count = 0

                    for ep in episodes:
                        ep_num = _safe_int(ep.get("number"))
                        if ep_num is None or ep_num < 0:
                            continue

                        watched_episode_keys.add((season_key, str(ep_num)))
                        completed_count += 1

                    per_season[season_key] = {
                        "completed": completed_count,
                        "aired": completed_count,
                        "complete": completed_count > 0,
                    }
                except Exception:
                    pass

            watched_episode_keys_by_show[tmdb_key] = watched_episode_keys
            season_summary_map[tmdb_key] = per_season

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Build resume/progress maps from sync/playback/episodes
    # ------------------------------------------------------------------
    for item in playback_items or []:
        try:
            show = item.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = _safe_int(ids.get("tmdb"))
            if tmdb_id is None:
                continue

            tmdb_key = str(tmdb_id)

            episode = item.get("episode") or {}
            season_num = _safe_int(episode.get("season"))
            ep_num = _safe_int(episode.get("number"))
            progress = _safe_float(item.get("progress"))

            if season_num is None or ep_num is None or progress is None:
                continue
            if progress < 0.1 or progress >= 95.0:
                continue

            runtime = _safe_int(episode.get("runtime"))
            resume_seconds = 0
            if runtime and runtime > 0:
                resume_seconds = int((progress / 100.0) * runtime * 60)

            episode_resume_map_by_show.setdefault(tmdb_key, {})[
                (str(season_num), str(ep_num))
            ] = {
                "progress": progress,
                "resume_seconds": resume_seconds,
                "playback_id": item.get("id"),
            }

            watched_episode_keys_by_show.setdefault(tmdb_key, set())
            season_summary_map.setdefault(tmdb_key, {})

            season_key = str(season_num)
            season_summary_map[tmdb_key].setdefault(
                season_key,
                {"completed": 0, "aired": 0, "complete": False},
            )

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Roll up season and show summaries from watched + resume episode maps
    # ------------------------------------------------------------------
    for tmdb_key in set(
        list(watched_episode_keys_by_show.keys())
        + list(episode_resume_map_by_show.keys())
    ):
        watched_keys = watched_episode_keys_by_show.get(tmdb_key, set()) or set()
        resume_map = episode_resume_map_by_show.get(tmdb_key, {}) or {}

        all_keys = set(watched_keys)
        all_keys.update(resume_map.keys())

        per_season = season_summary_map.setdefault(tmdb_key, {})

        season_numbers = set()
        for season_num, _ in all_keys:
            season_numbers.add(str(season_num))

        total_aired = 0
        total_completed = 0

        for season_key in season_numbers:
            season_entries = {k for k in all_keys if str(k[0]) == season_key}
            watched_count = sum(1 for k in season_entries if k in watched_keys)
            aired_count = len(season_entries)

            complete_flag = aired_count > 0 and watched_count >= aired_count

            per_season[season_key] = {
                "aired": aired_count,
                "completed": watched_count,
                "complete": complete_flag,
            }

            total_aired += aired_count
            total_completed += watched_count

        show_summary_map[tmdb_key] = {
            "aired": total_aired,
            "completed_count": total_completed,
            "completed": total_aired > 0 and total_completed >= total_aired,
        }

    data = {
        "show_summary_map": show_summary_map,
        "season_summary_map": season_summary_map,
        "watched_episode_keys_by_show": watched_episode_keys_by_show,
        "episode_resume_map_by_show": episode_resume_map_by_show,
    }

    _set_cached_tv_progress_maps(data)
    return data


def trakt_mark_movie_watched(tmdb_id):
    movie = _movie_ids_payload(tmdb_id)
    if movie is None:
        giptv.notification(ADDON.getAddonInfo("name"), "Missing TMDb ID", icon="ERROR")
        return False

    result = trakt_request(
        "sync/history",
        method="POST",
        data={"movies": [movie]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("movies")
        return True

    return False


def trakt_unmark_movie_watched(tmdb_id):
    movie = _movie_ids_payload(tmdb_id)
    if movie is None:
        giptv.notification(ADDON.getAddonInfo("name"), "Missing TMDb ID", icon="ERROR")
        return False

    result = trakt_request(
        "sync/history/remove",
        method="POST",
        data={"movies": [movie]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("movies")
        return True

    return False


def trakt_mark_show_watched(tmdb_id):
    show = _show_ids_payload(tmdb_id)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing show TMDb ID", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_unmark_show_watched(tmdb_id):
    show = _show_ids_payload(tmdb_id)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing show TMDb ID", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history/remove",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_mark_season_watched(tmdb_id, season):
    show = _season_show_payload(tmdb_id, season)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing season metadata", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_unmark_season_watched(tmdb_id, season):
    show = _season_show_payload(tmdb_id, season)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing season metadata", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history/remove",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_mark_episode_watched(tmdb_id, season, episode):
    show = _episode_show_payload(tmdb_id, season, episode)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing episode metadata", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_unmark_episode_watched(tmdb_id, season, episode):
    show = _episode_show_payload(tmdb_id, season, episode)
    if show is None:
        giptv.notification(
            ADDON.getAddonInfo("name"), "Missing episode metadata", icon="ERROR"
        )
        return False

    result = trakt_request(
        "sync/history/remove",
        method="POST",
        data={"shows": [show]},
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_scrobble_movie(action, tmdb_id, progress):
    if action not in ("start", "pause", "stop"):
        return False

    data = _movie_scrobble_payload(tmdb_id, progress)
    if data is None:
        return False

    result = trakt_request(
        f"scrobble/{action}",
        method="POST",
        data=data,
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("movies")
        return True

    return False


def trakt_scrobble_episode(action, tmdb_id, season, episode, progress):
    if action not in ("start", "pause", "stop"):
        return False

    data = _episode_scrobble_payload(tmdb_id, season, episode, progress)
    if data is None:
        return False

    result = trakt_request(
        f"scrobble/{action}",
        method="POST",
        data=data,
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache("episodes")
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_remove_playback(playback_id):
    playback_id = _safe_int(playback_id)
    if playback_id is None:
        return False

    result = trakt_request(
        f"sync/playback/{playback_id}",
        method="DELETE",
        with_auth=True,
    )
    if result is not None:
        _invalidate_playback_cache()
        _invalidate_tv_progress_maps_cache()
        return True

    return False


def trakt_clear_movie_playback(tmdb_id):
    playback = trakt_get_movie_playback(tmdb_id)
    if not playback:
        return True
    return trakt_remove_playback(playback.get("id"))


def trakt_clear_episode_playback(tmdb_id, season, episode):
    playback = trakt_get_episode_playback(tmdb_id, season, episode)
    if not playback:
        return True

    ok = trakt_remove_playback(playback.get("id"))
    if ok:
        _invalidate_show_progress_cache(tmdb_id)
        _invalidate_tv_progress_maps_cache()
    return ok


def trakt_save_movie_progress(tmdb_id, progress, current_time=None, total_time=None):
    tmdb_id = _safe_int(tmdb_id)
    progress = _normalize_progress(progress)

    if tmdb_id is None or progress is None:
        return False

    if progress <= 0:
        return True

    if progress >= 95.0:
        return trakt_clear_movie_playback(tmdb_id)

    return trakt_scrobble_movie("pause", tmdb_id, progress)


def trakt_save_episode_progress(
    tmdb_id,
    season,
    episode,
    progress,
    current_time=None,
    total_time=None,
):
    tmdb_id = _safe_int(tmdb_id)
    season = _safe_int(season)
    episode = _safe_int(episode)
    progress = _normalize_progress(progress)

    if tmdb_id is None or season is None or episode is None or progress is None:
        return False

    if progress <= 0:
        return True

    if progress >= 95.0:
        return trakt_clear_episode_playback(tmdb_id, season, episode)

    return trakt_scrobble_episode("pause", tmdb_id, season, episode, progress)
