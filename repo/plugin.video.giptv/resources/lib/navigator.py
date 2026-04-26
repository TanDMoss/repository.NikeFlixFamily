# -*- coding: utf-8 -*-
import sys
import datetime
import time
import os
import json
import base64
import gc
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

import resources.apis.tmdb_helper as TMDbHelper
import resources.apis.xtream_api as xtream_api
import resources.lib.live_guide as live_guide
import resources.utils.giptv as giptv
from resources.utils import settings
from resources.lib.manager.fetch_manager import cache_handler
from resources.lib.manager.epg_manager import (
    get_now_next,
    get_xmltv_index,
    resolve_xmltv_channel_id,
    set_catchup_channels,
)
from resources.lib.cache.picon_cache import get_picon
import resources.utils.config as config
from resources.utils.xtream import STATE
from resources.apis import trakt_api
from resources.lib.manager.index_manager import _read_index

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo("path")
ADDON_ID = ADDON.getAddonInfo("id")

GLOBAL_FANART = os.path.join(ADDON_PATH, "fanart.png")
LIVE_ICON = os.path.join(ADDON_PATH, "resources", "media", "thumb", "tv.png")
SERIES_ICON = os.path.join(ADDON_PATH, "resources", "media", "thumb", "series.png")
MOVIE_ICON = os.path.join(ADDON_PATH, "resources", "media", "thumb", "movies.png")
SEARCH_ICON = os.path.join(ADDON_PATH, "resources", "media", "thumb", "search.png")
WATCHED_ICON = os.path.join(ADDON_PATH, "resources", "media", "thumb", "watched.png")
FAVOURITES_ICON = os.path.join(
    ADDON_PATH, "resources", "media", "thumb", "favourite.png"
)

if len(sys.argv) > 1 and sys.argv[1].isdigit():
    PLUGIN_HANDLE = int(sys.argv[1])
else:
    PLUGIN_HANDLE = -1

tmdb_helper = TMDbHelper.TMDbHelper()
DEFAULT_PAGE_SIZE = 40


# ---------------------------------------------------------------------------
# LRU Cache
# ---------------------------------------------------------------------------


class LRUCache:
    def __init__(self, max_items=300):
        self.max_items = max_items
        self.data = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        return self.data[key]

    def set(self, key, value):
        self.data[key] = value
        self.data.move_to_end(key)
        while len(self.data) > self.max_items:
            self.data.popitem(last=False)

    def clear(self):
        self.data.clear()


_current_items = LRUCache(max_items=20)
_picon_memory_cache = LRUCache(max_items=200)
_xmltv_channel_cache = LRUCache(max_items=500)
_tmdb_id_memory_cache = LRUCache(max_items=2000)
_tmdb_details_cache = LRUCache(max_items=500)

# In-memory index lookup dicts built once per index type, keyed by tmdb_id
_index_tmdb_map = {}  # {"vod": {tmdb_id: [items]}, "series": {tmdb_id: [items]}}
_live_guide_runtime_cache = LRUCache(max_items=4)
LIVE_GUIDE_TTL_SECONDS = 900


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _ensure_ready():
    return config.ensure_api_ready()


def _plugin_url(**params):
    return sys.argv[0] + "?" + urlparse.urlencode(params)


def _encode_meta(meta_dict):
    try:
        raw = json.dumps(meta_dict, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def _safe_int(value, default=0):
    try:
        if value in (None, "", "None", "null"):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        if value in (None, "", "None", "null"):
            return default
        return float(value)
    except Exception:
        return default


def _set_tag_year(tag, value):
    try:
        if value in (None, "", "0", 0):
            return
        tag.setYear(int(value))
    except Exception:
        pass


def _set_tag_rating(tag, value):
    try:
        if value in (None, "", "0", 0):
            return
        rating_value = float(value)
        try:
            tag.setRating(rating_value)
        except TypeError:
            tag.setRating(rating_value, 10)
    except Exception:
        pass


def _safe_nonempty_text(value):
    value = (value or "").strip()
    return value or None


def _normalize_search_query(value):
    return (value or "").strip().lower()


def _normalize_title(value):
    return (value or "").strip().lower()


def _paginate_items(items, page, page_size=DEFAULT_PAGE_SIZE):
    if not isinstance(items, list):
        giptv.log(
            "[NAV] _paginate_items received non-list type={}".format(
                type(items).__name__
            ),
            xbmc.LOGWARNING,
        )
        items = []

    page = max(1, _safe_int(page, 1))
    start = (page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]
    has_next = end < len(items)
    return sliced, has_next, page


def _add_dir_items(items):
    if PLUGIN_HANDLE < 0:
        return

    if items:
        xbmcplugin.addDirectoryItems(PLUGIN_HANDLE, items, len(items))

    xbmcplugin.endOfDirectory(
        PLUGIN_HANDLE,
        succeeded=True,
        cacheToDisc=False,
    )


def _show_filter_keyboard(title):
    keyboard = xbmc.Keyboard("", title)
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None
    value = keyboard.getText().strip().lower()
    return value or None


def _apply_offset_minutes(timestamp, offset_minutes):
    return timestamp + (offset_minutes * 60)


def _fmt_time(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def _epg_progress(start_ts, end_ts):
    now = int(time.time())
    if end_ts <= start_ts:
        return 0
    return max(0, min(100, int((now - start_ts) * 100 / (end_ts - start_ts))))


def _progress_bar(percent, width=10):
    filled = int(width * percent / 100)
    return "●" * filled + "○" * (width - filled)


def _slim_search_items(items):
    slim = []
    for item in items or []:
        name = (
            item.get("name", "")
            or item.get("title", "")
            or item.get("stream_display_name", "")
        )
        slim.append(
            {
                "name": name,
                "lower": _normalize_title(name),
                "stream_id": item.get("stream_id", ""),
                "series_id": item.get("series_id", ""),
                "category_id": item.get("category_id", ""),
            }
        )
    return slim


def _store_current_items(stream_type, category_id, items):
    _current_items.set(f"{stream_type}_{category_id}", _slim_search_items(items))


def get_current_items(stream_type, category_id):
    return _current_items.get(f"{stream_type}_{category_id}", [])


# ---------------------------------------------------------------------------
# TMDb ID extraction / normalisation
# ---------------------------------------------------------------------------


def _extract_tmdb_id(data):
    return (
        data.get("tmdb")
        or data.get("tmdb_id")
        or data.get("tmdbId")
        or data.get("tmdbID")
        or data.get("imdb_id")
        or (data.get("info", {}) or {}).get("tmdb")
        or (data.get("info", {}) or {}).get("tmdb_id")
        or None
    )


def _normalize_tmdb_id(value):
    value = str(value or "").strip()
    return value if value.isdigit() else ""


def _clean_title_for_tmdb(title):
    value = str(title or "").strip()

    value = re.sub(r"\s*-\s*\d{4}$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\(\d{4}\)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\[\d{4}\]$", "", value, flags=re.IGNORECASE)

    junk_patterns = [
        r"\b4k/uhd\b",
        r"\b4k uhd\b",
        r"\buhd\b",
        r"\b4k\b",
        r"\bfhd\b",
        r"\bhd\b",
        r"\b2160p\b",
        r"\b1080p\b",
        r"\b720p\b",
        r"\bbluray\b",
        r"\bblu[- ]?ray\b",
        r"\bbrrip\b",
        r"\bwebrip\b",
        r"\bweb[- ]?dl\b",
        r"\bhdr\b",
        r"\bdv\b",
        r"\batmos\b",
        r"\bremux\b",
        r"\bx264\b",
        r"\bx265\b",
        r"\bhevc\b",
        r"\b4k-nf\b",
        r"\bnf-do\b",
        r"\b4k-top\b",
        r"\b4k-mrvl\b",
        r"\bnf\b",
        r"\bamzn\b",
        r"\bdsnp\b",
        r"\bhmax\b",
        r"\btop\b",
        r"\bmrvl\b",
        r"\bnetflix\b",
        r"\bdual audio\b",
        r"\bmulti audio\b",
        r"\bproper\b",
        r"\brepack\b",
        r"\bextended\b",
        r"\buncut\b",
        r"\bsubbed\b",
        r"\bdubbed\b",
        r"\beng\b",
        r"\bfr\b",
        r"\bit\b",
        r"\bes\b",
        r"\bde\b",
        r"\bpt\b",
        r"\bnl\b",
        r"\bpl\b",
        r"\bru\b",
        r"\btr\b",
        r"\bar\b",
        r"\bjp\b",
        r"\bkr\b",
    ]

    for pattern in junk_patterns:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)

    value = re.sub(r"\(\s*[a-z]{2}\s*\)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[\s*[a-z]{2}\s*\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"-\s*[a-z]{2,8}$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


# ---------------------------------------------------------------------------
# Cached TMDb lookups
# ---------------------------------------------------------------------------


def _movie_id_cache_key(stream_name, year_hint=""):
    return f"{_clean_title_for_tmdb(stream_name)}|{year_hint or ''}"


def _series_id_cache_key(series_name, year_hint=""):
    return f"{_clean_title_for_tmdb(series_name)}|{year_hint or ''}"


def _resolve_movie_tmdb_id_cached(stream_name, year_hint=""):
    cache_key = _movie_id_cache_key(stream_name, year_hint)
    cached = _tmdb_id_memory_cache.get(f"movie:{cache_key}")
    if cached is not None:
        return cached

    db_cache_key = f"{STATE.username}_movie_title_id_{cache_key}"
    cached_db = cache_handler.get("tmdb_data", db_cache_key)
    if cached_db:
        tmdb_id = str(cached_db.get("tmdb_id") or "")
        _tmdb_id_memory_cache.set(f"movie:{cache_key}", tmdb_id)
        return tmdb_id

    clean_title = _clean_title_for_tmdb(stream_name)
    tmdb_id = _normalize_tmdb_id(
        tmdb_helper.search_movie_id(clean_title, year=year_hint)
    )
    cache_handler.set("tmdb_data", db_cache_key, {"tmdb_id": tmdb_id})
    _tmdb_id_memory_cache.set(f"movie:{cache_key}", tmdb_id)
    return tmdb_id


def _resolve_series_tmdb_id_cached(series_name, year_hint=""):
    cache_key = _series_id_cache_key(series_name, year_hint)
    cached = _tmdb_id_memory_cache.get(f"series:{cache_key}")
    if cached is not None:
        return cached

    db_cache_key = f"{STATE.username}_series_title_id_{cache_key}"
    cached_db = cache_handler.get("tmdb_data", db_cache_key)
    if cached_db:
        tmdb_id = str(cached_db.get("tmdb_id") or "")
        _tmdb_id_memory_cache.set(f"series:{cache_key}", tmdb_id)
        return tmdb_id

    clean_title = _clean_title_for_tmdb(series_name)
    tmdb_id = _normalize_tmdb_id(
        tmdb_helper.search_series_id(clean_title, year=year_hint)
    )
    cache_handler.set("tmdb_data", db_cache_key, {"tmdb_id": tmdb_id})
    _tmdb_id_memory_cache.set(f"series:{cache_key}", tmdb_id)
    return tmdb_id


def _get_tmdb_movie_details_cached(tmdb_id):
    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return None
    key = f"movie:{tmdb_id}"
    cached = _tmdb_details_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = tmdb_helper.get_movie_details(tmdb_id)
    except Exception:
        data = None
    _tmdb_details_cache.set(key, data)
    return data


def _get_tmdb_series_details_cached(tmdb_id):
    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return None
    key = f"series:{tmdb_id}"
    cached = _tmdb_details_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = tmdb_helper.get_series_details(tmdb_id)
    except Exception:
        data = None
    _tmdb_details_cache.set(key, data)
    return data


def _get_tmdb_season_details_cached(tmdb_id, season_num):
    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return None
    key = f"season:{tmdb_id}:{season_num}"
    cached = _tmdb_details_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = tmdb_helper.get_season_details(tmdb_id, int(season_num))
    except Exception:
        data = None
    _tmdb_details_cache.set(key, data)
    return data


def _get_tmdb_episode_details_cached(tmdb_id, season_num, episode_num):
    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return None
    key = f"episode:{tmdb_id}:{season_num}:{episode_num}"
    cached = _tmdb_details_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = tmdb_helper.get_episode_details(
            tmdb_id, int(season_num), int(episode_num)
        )
    except Exception:
        data = None
    _tmdb_details_cache.set(key, data)
    return data


# ---------------------------------------------------------------------------
# Art / UI helpers
# ---------------------------------------------------------------------------


def _build_art(thumb="", poster="", fanart="", icon="", fallback="DefaultVideo.png"):
    thumb = thumb or poster or fanart or icon or fallback
    poster = poster or thumb or fanart or icon or fallback
    fanart = fanart or poster or thumb or icon or fallback
    icon = icon or thumb or poster or fanart or fallback
    return {"thumb": thumb, "poster": poster, "fanart": fanart, "icon": icon}


def _get_picon_cached(stream_id, stream_icon, category_id):
    key = (str(stream_id), stream_icon or "", str(category_id or ""))
    cached = _picon_memory_cache.get(key)
    if cached is not None:
        return cached
    value = get_picon(stream_id, stream_icon, category_id)
    _picon_memory_cache.set(key, value)
    return value


def _resolve_xmltv_channel_id_cached(stream):
    stream_id = str(stream.get("stream_id", ""))
    cached = _xmltv_channel_cache.get(stream_id)
    if cached is not None:
        return cached
    value = resolve_xmltv_channel_id(stream)
    _xmltv_channel_cache.set(stream_id, value)
    return value


def _label_with_marker(label, watched=False, progress=None):
    base = label or ""
    try:
        progress = int(float(progress)) if progress is not None else None
    except Exception:
        progress = None

    if watched:
        return f"[COLOR limegreen]\u2714[/COLOR] {base}"
    if progress is not None and progress > 0:
        return f"[COLOR orange]{progress}%[/COLOR] {base}"
    return base


def _apply_tmdb_art_to_listitem(li, art, tmdb_id=None, fallback="DefaultVideo.png"):
    """Apply art dict to a listitem and optionally set tmdb properties."""
    li.setArt(
        _build_art(
            thumb=art.get("thumb", "") or art.get("poster", ""),
            poster=art.get("poster", ""),
            fanart=art.get("fanart", ""),
            icon=art.get("thumb", "") or art.get("poster", ""),
            fallback=fallback,
        )
    )
    if tmdb_id:
        li.setProperty("tmdbnumber", str(tmdb_id))
        li.setProperty("imdbnumber", str(tmdb_id))
        try:
            li.getVideoInfoTag().setUniqueIDs({"tmdb": str(tmdb_id)}, "tmdb")
        except Exception:
            pass


def _apply_basic_tag(tag, title, plot="", media_type="movie", year=None, rating=None):
    """Set common video info tag fields."""
    try:
        tag.setTitle(title)
    except Exception:
        pass
    try:
        tag.setPlot(plot)
    except Exception:
        pass
    try:
        tag.setMediaType(media_type)
    except Exception:
        pass
    if year is not None:
        _set_tag_year(tag, year)
    if rating is not None:
        _set_tag_rating(tag, rating)


# ---------------------------------------------------------------------------
# Index lookup (O(1) by tmdb_id after first build)
# ---------------------------------------------------------------------------


def _build_index_tmdb_map(index_type):
    """Build and cache a dict mapping tmdb_id -> [items] for fast lookups."""
    if index_type in _index_tmdb_map:
        return _index_tmdb_map[index_type]

    try:
        index_items = _read_index(index_type) or []
    except Exception:
        index_items = []

    mapping = {}
    for item in index_items:
        tmdb = str(item.get("tmdb") or "").strip()
        if tmdb:
            mapping.setdefault(tmdb, []).append(item)

    _index_tmdb_map[index_type] = mapping
    return mapping


def _find_all_index_matches(index_type, title="", tmdb_id=""):
    tmdb_id = str(tmdb_id or "").strip()
    wanted = _normalize_title(title)

    # Fast path: O(1) lookup by tmdb_id
    if tmdb_id:
        mapping = _build_index_tmdb_map(index_type)
        if tmdb_id in mapping:
            return mapping[tmdb_id]

    # Fallback: linear title scan
    try:
        index_items = _read_index(index_type) or []
    except Exception:
        index_items = []

    results = []
    seen = set()

    for item in index_items:
        try:
            item_title = _normalize_title(item.get("title") or item.get("name") or "")
            item_id = str(
                item.get("id") or item.get("stream_id") or item.get("series_id") or ""
            )

            if not wanted or not item_title:
                continue

            if not (
                wanted == item_title or wanted in item_title or item_title in wanted
            ):
                continue

            dedupe_key = "{}|{}|{}".format(
                item_id, str(item.get("category_id") or ""), item_title
            )
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            results.append(item)
        except Exception:
            pass

    return results


def _find_best_index_match(index_type, title="", tmdb_id=""):
    matches = _find_all_index_matches(index_type, title=title, tmdb_id=tmdb_id)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Parallel fetch helpers
# ---------------------------------------------------------------------------


def _parallel_fetch(tasks):
    """
    Run multiple callables in parallel.
    tasks: list of (key, callable, *args)
    Returns dict of {key: result}
    """
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as pool:
        futures = {pool.submit(fn, *args): key for key, fn, *args in tasks}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = None
    return results


def _fetch_trakt_vod_data():
    """Fetch resume map and watched IDs for VOD in parallel."""
    fetched = _parallel_fetch(
        [
            ("resume_map", trakt_api.trakt_get_movie_resume_map),
            ("watched_ids", trakt_api.trakt_get_watched_movie_ids),
        ]
    )
    return (
        fetched.get("resume_map") or {},
        fetched.get("watched_ids") or set(),
    )


def _fetch_trakt_episode_data(tmdb_id):
    """Fetch watched episode keys and resume map for a series in parallel."""
    fetched = _parallel_fetch(
        [
            ("watched_keys", trakt_api.trakt_get_show_watched_episode_keys, tmdb_id),
            ("resume_map", trakt_api.trakt_get_episode_resume_map, tmdb_id),
        ]
    )
    return (
        fetched.get("watched_keys") or set(),
        fetched.get("resume_map") or {},
    )


# ---------------------------------------------------------------------------
# Memory / diagnostics
# ---------------------------------------------------------------------------


def _log_memory_caches(context=""):
    try:
        giptv.log(
            f"[MEM] {context} current_items={len(_current_items.data)} "
            f"picons={len(_picon_memory_cache.data)} "
            f"xmltv_ids={len(_xmltv_channel_cache.data)} "
            f"tmdb_ids={len(_tmdb_id_memory_cache.data)} "
            f"tmdb_details={len(_tmdb_details_cache.data)}",
            xbmc.LOGINFO,
        )
    except Exception:
        pass


def _trim_route_memory(is_live=False):
    _picon_memory_cache.clear()
    if not is_live:
        _xmltv_channel_cache.clear()
    # gc.collect()


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------


def _open_root_menu():
    try:
        xbmc.executebuiltin(
            "ActivateWindow(Videos,plugin://{}/?mode=root_menu,return)".format(ADDON_ID)
        )
    except Exception:
        try:
            xbmc.executebuiltin(
                "Container.Update(plugin://{}/?mode=root_menu&_={})".format(
                    ADDON_ID, int(time.time() * 1000)
                )
            )
        except Exception:
            pass


def _notify_and_go_home(message="Server unavailable"):
    try:
        giptv.notification(ADDON.getAddonInfo("name"), message, icon="ERROR")
    except Exception:
        pass
    xbmc.sleep(250)
    _open_root_menu()


def _notify_and_open_settings(message="Server not configured correctly"):
    try:
        giptv.notification(ADDON.getAddonInfo("name"), message, icon="ERROR")
    except Exception:
        pass
    xbmc.sleep(250)
    try:
        giptv.open_settings()
    except Exception:
        pass


def _is_invalid_xtream_payload(data):
    if data is None:
        return True
    if isinstance(data, list):
        return False
    if isinstance(data, dict):
        if not data:
            return True
        try:
            lowered = json.dumps(data).lower()
        except Exception:
            lowered = str(data).lower()
        bad_markers = [
            "invalid",
            "unauthorized",
            "forbidden",
            "expired",
            "denied",
            "error",
            "available at the moment",
            "access denied",
            "auth",
        ]
        return any(marker in lowered for marker in bad_markers)
    return True


def _safe_category_list(stream_type):
    cache_key = f"{STATE.username}_{stream_type}"
    category_list = cache_handler.get("categories", cache_key)

    if category_list is not None and not isinstance(category_list, list):
        giptv.log(
            "[NAV] bad cached categories key={} type={}".format(
                cache_key, type(category_list).__name__
            ),
            xbmc.LOGWARNING,
        )
        category_list = None

    if not category_list:
        category_list = xtream_api.categories(stream_type)

    if _is_invalid_xtream_payload(category_list):
        return None

    return category_list


def _safe_stream_list(stream_type, category_id):
    cache_key = f"{STATE.username}_{stream_type}_{category_id}"
    stream_list = cache_handler.get(stream_type, cache_key)

    if stream_list is not None and not isinstance(stream_list, list):
        giptv.log(
            "[NAV] bad cached streams key={} type={}".format(
                cache_key, type(stream_list).__name__
            ),
            xbmc.LOGWARNING,
        )
        stream_list = None

    if not stream_list:
        stream_list = xtream_api.streams_by_category(stream_type, category_id)

    if _is_invalid_xtream_payload(stream_list):
        return None

    return stream_list


def _has_category_matches(category_list, query):
    q = _normalize_search_query(query)
    if not q:
        return False
    for c in category_list or []:
        if q in (c.get("category_name", "") or "").lower():
            return True
    return False


def _stream_matches_query(item, query):
    q = _normalize_search_query(query)
    if not q:
        return False
    name = _normalize_search_query(item.get("name") or "")
    title = _normalize_search_query(item.get("title") or "")
    display = _normalize_search_query(item.get("stream_display_name") or "")
    return q in name or q in title or q in display


def _is_trakt_ready():
    try:
        return trakt_api.trakt_is_authenticated()
    except Exception:
        return False


def _get_show_progress_summary_cached(tmdb_id):
    try:
        data = trakt_api.trakt_get_show_watched_progress(tmdb_id)
    except Exception:
        data = None

    if not data:
        return {"completed": False, "aired": 0, "completed_count": 0, "season_map": {}}

    season_map = {}
    for season in data.get("seasons", []) or []:
        try:
            s_no = str(season.get("number"))
            aired = int(season.get("aired") or len(season.get("episodes") or []))
            completed_eps = sum(
                1 for ep in season.get("episodes", []) or [] if ep.get("completed")
            )
            season_map[s_no] = {
                "aired": aired,
                "completed": completed_eps,
                "complete": aired > 0 and completed_eps >= aired,
            }
        except Exception:
            pass

    aired_total = int(data.get("aired") or 0)
    completed_total = int(data.get("completed") or 0)

    return {
        "completed": aired_total > 0 and completed_total >= aired_total,
        "aired": aired_total,
        "completed_count": completed_total,
        "season_map": season_map,
    }


# ---------------------------------------------------------------------------
# Sort helpers
# ---------------------------------------------------------------------------


def _sort_streams(stream_list, mode):
    if not mode:
        return stream_list
    reverse = mode == "za"
    return sorted(
        stream_list,
        key=lambda s: _normalize_title(
            s.get("name") or s.get("title") or s.get("stream_display_name") or ""
        ),
        reverse=reverse,
    )


def _sort_categories(categories, mode):
    if not mode:
        return categories
    reverse = mode == "za"
    return sorted(
        categories, key=lambda c: c.get("category_name", "").lower(), reverse=reverse
    )


# ---------------------------------------------------------------------------
# Context menu / URL builders
# ---------------------------------------------------------------------------


def _add_giptv_context_menu(list_item, menu_url):
    list_item.addContextMenuItems(
        [("GIPTV Menu", f"RunPlugin({menu_url})")],
        replaceItems=False,
    )


def _build_category_menu_url(stream_type, category_id, category_name):
    from resources.lib.manager import sort_manager

    sort_label = sort_manager.get_sort_label("categories", stream_type)
    return giptv.build_url(
        action="open_context_window",
        title=category_name,
        name=category_name,
        item_id=f"category:{stream_type}:{category_id}",
        stream_type=stream_type,
        directory_type="categories",
        directory_id=stream_type,
        refresh_mode="list_categories",
        sort_label=sort_label,
        category_id=category_id,
        category_name=category_name,
        play_url="",
        thumb="",
        poster="",
        fanart="",
        icon="",
        plot="",
        rating="0",
        year="0",
        tmdb_id="",
        channel_id="",
        epg_channel_id="",
        has_archive="0",
    )


def _build_stream_menu_url(
    *,
    item_id,
    name,
    play_url,
    stream_type,
    thumb="",
    poster="",
    fanart="",
    icon="",
    plot="",
    rating="0",
    year="0",
    tmdb_id="",
    channel_id="",
    epg_channel_id="",
    has_archive="0",
    directory_type="",
    directory_id="",
    refresh_mode="",
    sort_label="",
    category_id="",
    category_name="",
    search_query="",
    page="1",
    season="",
    episode="",
    favourite_kind="playable",
    target_mode="",
    series_id="",
    series_name="",
    season_num="",
):
    return giptv.build_url(
        action="open_context_window",
        title=name,
        item_id=item_id,
        name=name,
        play_url=play_url,
        stream_type=stream_type,
        thumb=thumb,
        poster=poster,
        fanart=fanart,
        icon=icon,
        plot=plot,
        rating=str(rating),
        year=str(year),
        tmdb_id=tmdb_id,
        channel_id=channel_id,
        epg_channel_id=epg_channel_id,
        has_archive=str(has_archive),
        directory_type=directory_type,
        directory_id=directory_id,
        refresh_mode=refresh_mode,
        sort_label=sort_label,
        category_id=category_id,
        category_name=category_name,
        search_query=search_query or "",
        page=str(page or "1"),
        season=str(season or ""),
        episode=str(episode or ""),
        favourite_kind=favourite_kind,
        target_mode=target_mode,
        series_id=str(series_id or ""),
        series_name=series_name or "",
        season_num=str(season_num or ""),
    )


# ---------------------------------------------------------------------------
# Pagination nav items
# ---------------------------------------------------------------------------


def _prev_page_item(mode, page, **extra):
    li = xbmcgui.ListItem(label="[COLOR orange]\u25c0 Previous Page[/COLOR]")
    li.setArt({"icon": "DefaultFolderBack.png", "thumb": "DefaultFolderBack.png"})
    return (_plugin_url(mode=mode, page=str(page - 1), **extra), li, True)


def _next_page_item(mode, page, **extra):
    li = xbmcgui.ListItem(label="[COLOR orange]Next Page \u25b6[/COLOR]")
    li.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
    return (_plugin_url(mode=mode, page=str(page + 1), **extra), li, True)


# ---------------------------------------------------------------------------
# Live guide
# ---------------------------------------------------------------------------


def _live_guide_cache_key():
    return "{}_{}_live_guide_streams".format(
        getattr(STATE, "username", "") or "default",
        getattr(STATE, "server", "") or "server",
    )


def _fetch_live_guide_streams():
    cache_key = _live_guide_cache_key()
    cached = _live_guide_runtime_cache.get(cache_key)
    if cached and time.time() - cached.get("timestamp", 0) < LIVE_GUIDE_TTL_SECONDS:
        return cached.get("streams") or []

    category_names = {}
    category_list = _safe_category_list(xtream_api.LIVE_TYPE) or []
    for category in category_list:
        if not isinstance(category, dict):
            continue
        category_id = category.get("category_id")
        if category_id in (None, ""):
            continue
        category_names[str(category_id)] = category.get("category_name", "")

    streams = xtream_api.get_all_live_streams()
    if streams is None:
        streams = xtream_api.get_live_streams()

    enriched = []
    for stream in streams or []:
        if not isinstance(stream, dict):
            continue
        row = dict(stream)
        category_id = row.get("category_id")
        row["category_name"] = row.get("category_name") or category_names.get(
            str(category_id), ""
        )
        enriched.append(row)

    _live_guide_runtime_cache.set(
        cache_key, {"timestamp": time.time(), "streams": enriched}
    )
    return enriched


def _set_live_guide_info(list_item, title, plot=""):
    try:
        tag = list_item.getVideoInfoTag()
        tag.setTitle(title)
        tag.setPlot(plot or title)
        tag.setMediaType("video")
    except Exception:
        try:
            list_item.setInfo("video", {"title": title, "plot": plot or title})
        except Exception:
            pass


def _make_live_guide_folder(label, url, description="", art=""):
    li = xbmcgui.ListItem(label=label)
    art = art or LIVE_ICON
    li.setArt({"icon": art, "thumb": art, "fanart": art or GLOBAL_FANART})
    _set_live_guide_info(li, label, description)
    return (url, li, True)


def list_live_guide(section_key=""):
    if not _ensure_ready():
        return

    items = []
    section_key = (section_key or "").strip()

    if not section_key:
        for section in live_guide.sections():
            items.append(
                _make_live_guide_folder(
                    section["label"],
                    _plugin_url(mode="live_guide", section=section["key"]),
                    section.get("description", ""),
                    section.get("art", ""),
                )
            )
        xbmcplugin.setPluginCategory(PLUGIN_HANDLE, "Live TV Guide")
        xbmcplugin.setContent(PLUGIN_HANDLE, "videos")
        _add_dir_items(items)
        return

    groups = live_guide.groups_for_section(section_key)
    if not groups:
        giptv.notification(ADDON.getAddonInfo("name"), "No guide groups found", icon="INFO")
        _add_dir_items([])
        return

    for group in groups:
        items.append(
            _make_live_guide_folder(
                group["label"],
                _plugin_url(mode="live_guide_group", group_key=group["key"], page="1"),
                "Dynamic live TV group",
                group.get("art", ""),
            )
        )

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, "Live TV Guide")
    xbmcplugin.setContent(PLUGIN_HANDLE, "videos")
    _add_dir_items(items)


def list_live_guide_group(group_key, page=1):
    if not _ensure_ready():
        return

    group = live_guide.get_group(group_key)
    if not group:
        giptv.notification(ADDON.getAddonInfo("name"), "Unknown guide group", icon="ERROR")
        _add_dir_items([])
        return

    page = max(1, _safe_int(page, 1))
    streams = live_guide.match_streams(_fetch_live_guide_streams(), group_key)
    page_streams, has_next, page = _paginate_items(streams, page)
    items = []

    if page > 1:
        items.append(_prev_page_item("live_guide_group", page, group_key=group_key))

    selected_format = settings.get_stream_format(ADDON)

    for stream in page_streams:
        stream_id = str(stream.get("stream_id") or stream.get("id") or "")
        if not stream_id:
            continue

        stream_name = (
            stream.get("name")
            or stream.get("title")
            or stream.get("stream_display_name")
            or "Unknown Channel"
        )
        display_name = live_guide.clean_display_name(stream_name)
        ext = stream.get("container_extension", "ts")
        if selected_format == "ts":
            ext = "ts"
        elif selected_format == "m3u8":
            ext = "m3u8"

        stream_icon = _get_picon_cached(
            stream_id, stream.get("stream_icon"), stream.get("category_id")
        )
        play_url = xtream_api.build_stream_url(
            stream_id=stream_id,
            stream_type="live",
            container_extension=ext,
        )
        if not play_url:
            continue

        category_label = live_guide.clean_description(
            stream.get("category_name") or group.get("label", "")
        ) or group.get("label", "")
        art_dict = _build_art(
            thumb=stream_icon or group.get("art", ""),
            poster=stream_icon or group.get("art", ""),
            fanart=stream_icon or group.get("art", ""),
            icon=stream_icon or group.get("art", ""),
            fallback="DefaultVideo.png",
        )
        list_item = xbmcgui.ListItem(label=display_name)
        list_item.setProperty("IsPlayable", "true")
        list_item.setProperty("IsLive", "true")
        list_item.setArt(art_dict)
        _set_live_guide_info(
            list_item,
            display_name,
            category_label,
        )

        metadata = {
            "thumb": art_dict.get("thumb", ""),
            "poster": art_dict.get("poster", ""),
            "fanart": art_dict.get("fanart", ""),
            "icon": art_dict.get("icon", ""),
            "plot": category_label,
            "rating": 0,
            "year": 0,
            "tmdb_id": "",
            "stream_type": "live",
            "channel_id": "",
            "stream_id": stream_id,
        }

        url = _plugin_url(
            mode="play_stream",
            url=play_url,
            name=display_name,
            meta=_encode_meta(metadata),
        )

        menu_url = _build_stream_menu_url(
            item_id=stream_id,
            name=display_name,
            play_url=play_url,
            stream_type="live",
            thumb=art_dict.get("thumb", ""),
            poster=art_dict.get("poster", ""),
            fanart=art_dict.get("fanart", ""),
            icon=art_dict.get("icon", ""),
            plot=category_label,
            rating="0",
            year="0",
            tmdb_id="",
            channel_id="",
            epg_channel_id=str(stream.get("epg_channel_id", "")),
            has_archive=str(stream.get("tv_archive", stream.get("has_archive", "0"))),
            directory_type="streams",
            directory_id=f"live_guide:{group_key}",
            refresh_mode="live_guide_group",
            sort_label="",
            category_id=str(stream.get("category_id", "")),
            category_name=category_label,
            search_query="",
            page=str(page),
            favourite_kind="playable",
            target_mode="play_stream",
        )
        _add_giptv_context_menu(list_item, menu_url)
        items.append((url, list_item, False))

    if has_next:
        items.append(_next_page_item("live_guide_group", page, group_key=group_key))

    xbmcplugin.setPluginCategory(
        PLUGIN_HANDLE, group.get("label", "Live Guide")
    )
    xbmcplugin.setContent(PLUGIN_HANDLE, "videos")
    _add_dir_items(items)
    _trim_route_memory(is_live=True)


# ---------------------------------------------------------------------------
# Continue Watching builders
# ---------------------------------------------------------------------------


def _make_continue_movie_item(tmdb_id, match_list, resume_data):
    details = _get_tmdb_movie_details_cached(tmdb_id) or {}
    art = (details.get("art") or {}) if details else {}

    title = details.get("title") or ""
    if not title and match_list:
        title = match_list[0].get("title") or "Continue Watching"

    progress = _safe_float((resume_data or {}).get("progress"), 0.0)
    if progress <= 0.0 or progress >= 98.0:
        return None

    li = xbmcgui.ListItem(
        label=_label_with_marker(f"[B]Continue:[/B] {title}", progress=progress)
    )
    _apply_tmdb_art_to_listitem(li, art, tmdb_id=tmdb_id)
    _apply_basic_tag(
        li.getVideoInfoTag(),
        title,
        plot=details.get("plot", ""),
        media_type="movie",
        year=details.get("year"),
        rating=details.get("rating"),
    )

    menu_url = _build_stream_menu_url(
        item_id=f"continue_movie:{tmdb_id}",
        name=title,
        play_url="",
        stream_type="vod",
        thumb=art.get("thumb", ""),
        poster=art.get("poster", ""),
        fanart=art.get("fanart", ""),
        icon=art.get("thumb", "") or art.get("poster", ""),
        plot=details.get("plot", ""),
        rating=str(details.get("rating") or "0"),
        year=str(details.get("year") or "0"),
        tmdb_id=str(tmdb_id),
        directory_type="continue",
        directory_id="movies",
        refresh_mode="continue_movies",
        favourite_kind="continue_folder",
        target_mode="continue_movie_versions",
    )
    _add_giptv_context_menu(li, menu_url)

    return (
        _plugin_url(mode="continue_movie_versions", tmdb_id=str(tmdb_id), title=title),
        li,
        True,
    )


def _make_continue_series_item(tmdb_id, match_list, playback_item):
    details = _get_tmdb_series_details_cached(tmdb_id) or {}
    art = (details.get("art") or {}) if details else {}

    title = details.get("title") or ""
    if not title and match_list:
        title = match_list[0].get("title") or "Continue Watching"

    progress = _safe_float((playback_item or {}).get("progress"), 0.0)
    if progress <= 0.0 or progress >= 98.0:
        return None

    li = xbmcgui.ListItem(
        label=_label_with_marker(f"[B]Continue:[/B] {title}", progress=progress)
    )
    _apply_tmdb_art_to_listitem(li, art, tmdb_id=tmdb_id, fallback="DefaultTVShows.png")
    _apply_basic_tag(
        li.getVideoInfoTag(),
        title,
        plot=details.get("plot", ""),
        media_type="tvshow",
        year=details.get("year"),
        rating=details.get("rating"),
    )

    menu_url = _build_stream_menu_url(
        item_id=f"continue_series:{tmdb_id}",
        name=title,
        play_url="",
        stream_type="series",
        thumb=art.get("thumb", ""),
        poster=art.get("poster", ""),
        fanart=art.get("fanart", ""),
        icon=art.get("thumb", "") or art.get("poster", ""),
        plot=details.get("plot", ""),
        rating=str(details.get("rating") or "0"),
        year=str(details.get("year") or "0"),
        tmdb_id=str(tmdb_id),
        directory_type="continue",
        directory_id="series",
        refresh_mode="continue_series",
        favourite_kind="continue_folder",
        target_mode="continue_series_versions",
    )
    _add_giptv_context_menu(li, menu_url)

    return (
        _plugin_url(mode="continue_series_versions", tmdb_id=str(tmdb_id), title=title),
        li,
        True,
    )


def _get_continue_watching_movie_items():
    out = []
    seen = set()

    try:
        trakt_resume_map = trakt_api.trakt_get_movie_resume_map()
    except Exception:
        trakt_resume_map = {}

    merged = [
        {
            "tmdb_id": str(tmdb_id),
            "progress": _safe_float((resume_data or {}).get("progress"), 0.0),
        }
        for tmdb_id, resume_data in (trakt_resume_map or {}).items()
    ]
    merged.sort(key=lambda x: x["progress"], reverse=True)

    # Prefetch TMDb details in parallel for all candidate IDs
    candidate_ids = [r["tmdb_id"] for r in merged if 0.0 < r["progress"] < 98.0]

    def _fetch_movie_detail(tid):
        return _get_tmdb_movie_details_cached(tid)

    if candidate_ids:
        with ThreadPoolExecutor(max_workers=min(len(candidate_ids), 6)) as pool:
            list(pool.map(_fetch_movie_detail, candidate_ids))

    for row in merged:
        try:
            tmdb_id = row["tmdb_id"]
            progress = row["progress"]

            if not tmdb_id or progress <= 0.0 or progress >= 98.0:
                continue
            if tmdb_id in seen:
                continue

            title = (_get_tmdb_movie_details_cached(tmdb_id) or {}).get("title") or ""
            match_list = _find_all_index_matches("vod", title=title, tmdb_id=tmdb_id)
            if not match_list:
                continue

            seen.add(tmdb_id)
            out.append((tmdb_id, match_list, {"progress": progress}))
        except Exception:
            pass

    return out[:6]


def _get_continue_watching_series_items():
    out = []
    seen = set()

    try:
        playback_items = trakt_api.trakt_get_playback("series")
    except Exception:
        playback_items = []

    merged = []
    for item in playback_items or []:
        try:
            show = item.get("show") or {}
            ids = show.get("ids") or {}
            episode = item.get("episode") or {}
            merged.append(
                {
                    "tmdb_id": str(ids.get("tmdb") or ""),
                    "title": show.get("title") or "",
                    "progress": _safe_float(item.get("progress"), 0.0),
                    "season": str(episode.get("season") or ""),
                    "episode": str(episode.get("number") or ""),
                    "source": "trakt",
                }
            )
        except Exception:
            pass

    merged.sort(key=lambda x: x["progress"], reverse=True)

    # Prefetch series details in parallel
    candidate_ids = [
        r["tmdb_id"] for r in merged if 0.0 < r["progress"] < 98.0 and r["tmdb_id"]
    ]
    if candidate_ids:
        with ThreadPoolExecutor(max_workers=min(len(candidate_ids), 6)) as pool:
            list(pool.map(_get_tmdb_series_details_cached, candidate_ids))

    for row in merged:
        try:
            tmdb_id = row["tmdb_id"]
            title = row["title"]
            progress = row["progress"]

            if not tmdb_id or progress <= 0.0 or progress >= 98.0:
                continue
            if tmdb_id in seen:
                continue

            match_list = _find_all_index_matches("series", title=title, tmdb_id=tmdb_id)
            if not match_list:
                continue

            seen.add(tmdb_id)
            out.append((tmdb_id, match_list, row))
        except Exception:
            pass

    return out[:6]


# ---------------------------------------------------------------------------
# Continue Watching version lists
# ---------------------------------------------------------------------------


def _find_current_vod_stream_from_match(index_entry, tmdb_id="", title=""):
    category_id = str(index_entry.get("category_id") or "")
    if not category_id:
        return None

    current_streams = _safe_stream_list("vod", category_id)
    if not isinstance(current_streams, list):
        return None

    wanted_tmdb = str(tmdb_id or "").strip()
    wanted_title = _normalize_title(title)

    exact_tmdb = []
    exact_title = []
    partial_title = []

    for stream in current_streams:
        try:
            stream_tmdb = _normalize_tmdb_id(_extract_tmdb_id(stream))
            stream_title = _normalize_title(
                stream.get("name")
                or stream.get("title")
                or stream.get("stream_display_name")
                or ""
            )

            if wanted_tmdb and stream_tmdb == wanted_tmdb:
                exact_tmdb.append(stream)
                continue

            if wanted_title and stream_title == wanted_title:
                exact_title.append(stream)
                continue

            if wanted_title and (
                wanted_title in stream_title or stream_title in wanted_title
            ):
                partial_title.append(stream)
        except Exception:
            pass

    if exact_tmdb:
        return exact_tmdb[0]
    if exact_title:
        return exact_title[0]
    if partial_title:
        return partial_title[0]

    return None


def list_continue_movie_versions(tmdb_id, title=""):
    if not _ensure_ready():
        return

    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return

    details = _get_tmdb_movie_details_cached(tmdb_id) or {}
    art = (details.get("art") or {}) if details else {}

    resume_map = {}
    try:
        resume_map = trakt_api.trakt_get_movie_resume_map()
    except Exception:
        pass

    resume_data = resume_map.get(str(tmdb_id)) or {}
    progress = _safe_float(resume_data.get("progress"), 0.0)

    matches = _find_all_index_matches("vod", title="", tmdb_id=tmdb_id)
    if not matches and title:
        matches = _find_all_index_matches("vod", title=title, tmdb_id=tmdb_id)

    items = []

    for entry in matches:
        try:
            category_id = str(entry.get("category_id") or "")
            category_name = entry.get("category_name", "Movies")

            current_stream = _find_current_vod_stream_from_match(
                entry,
                tmdb_id=tmdb_id,
                title=title or entry.get("title") or entry.get("name") or "",
            )

            stream_id = ""
            ext = "mp4"
            live_title = ""

            if current_stream:
                stream_id = str(
                    current_stream.get("stream_id")
                    or current_stream.get("movie_id")
                    or current_stream.get("vod_id")
                    or ""
                )
                ext = current_stream.get("container_extension", "mp4")
                live_title = (
                    current_stream.get("name")
                    or current_stream.get("title")
                    or current_stream.get("stream_display_name")
                    or ""
                )

            server_title = (
                live_title
                or entry.get("title")
                or entry.get("name")
                or title
                or "Continue Watching"
            )

            thumb = (
                art.get("thumb")
                or art.get("poster")
                or entry.get("thumb")
                or entry.get("poster")
                or ""
            )
            poster = art.get("poster") or thumb
            fanart = art.get("fanart") or poster
            icon = thumb or poster

            li = xbmcgui.ListItem(
                label=_label_with_marker(
                    "{} [COLOR grey]({})[/COLOR]".format(server_title, category_name),
                    progress=progress,
                )
            )
            li.setArt(_build_art(thumb=thumb, poster=poster, fanart=fanart, icon=icon))

            tag = li.getVideoInfoTag()
            _apply_basic_tag(
                tag,
                server_title,
                plot=details.get("plot", ""),
                media_type="movie",
                year=details.get("year"),
                rating=details.get("rating"),
            )

            if tmdb_id:
                li.setProperty("tmdbnumber", str(tmdb_id))
                li.setProperty("imdbnumber", str(tmdb_id))
                try:
                    tag.setUniqueIDs({"tmdb": str(tmdb_id)}, "tmdb")
                except Exception:
                    pass

            plot_value = details.get("plot") or ""
            rating_value = details.get("rating") or 0
            year_value = details.get("year") or 0

            play_url = ""
            if stream_id:
                try:
                    play_url = xtream_api.build_stream_url(
                        stream_id=stream_id,
                        stream_type="vod",
                        container_extension=ext,
                    )
                except Exception:
                    play_url = ""

            metadata = {
                "thumb": thumb,
                "poster": poster,
                "fanart": fanart,
                "icon": icon,
                "plot": plot_value,
                "rating": rating_value,
                "year": year_value,
                "tmdb_id": str(tmdb_id),
                "stream_type": "vod",
                "stream_id": stream_id,
            }

            if play_url:
                li.setProperty("IsPlayable", "true")
                url = _plugin_url(
                    mode="play_stream",
                    url=play_url,
                    name=server_title,
                    meta=_encode_meta(metadata),
                )
                menu_url = _build_stream_menu_url(
                    item_id=stream_id,
                    name=server_title,
                    play_url=play_url,
                    stream_type="vod",
                    thumb=thumb,
                    poster=poster,
                    fanart=fanart,
                    icon=icon,
                    plot=plot_value,
                    rating=str(rating_value or "0"),
                    year=str(year_value or "0"),
                    tmdb_id=str(tmdb_id),
                    category_id=category_id,
                    category_name=category_name,
                    favourite_kind="playable",
                    target_mode="play_stream",
                )
                _add_giptv_context_menu(li, menu_url)
                items.append((url, li, False))
            else:
                menu_url = _build_stream_menu_url(
                    item_id=str(entry.get("id") or ""),
                    name=server_title,
                    play_url="",
                    stream_type="vod",
                    thumb=thumb,
                    poster=poster,
                    fanart=fanart,
                    icon=icon,
                    plot=plot_value,
                    rating=str(rating_value or "0"),
                    year=str(year_value or "0"),
                    tmdb_id=str(tmdb_id),
                    category_id=category_id,
                    category_name=category_name,
                    favourite_kind="playable",
                    target_mode="list_streams",
                )
                _add_giptv_context_menu(li, menu_url)
                items.append(
                    (
                        _plugin_url(
                            mode="list_streams",
                            stream_type="vod",
                            category_id=category_id,
                            name=category_name,
                            search_query=_normalize_search_query(server_title),
                            page="1",
                        ),
                        li,
                        True,
                    )
                )

        except Exception as e:
            giptv.log(
                "[CONTINUE MOVIE VERSIONS] row failed: {}".format(e),
                xbmc.LOGWARNING,
            )

    xbmcplugin.setPluginCategory(
        PLUGIN_HANDLE, "Sources for {}".format(title or "Continue Watching")
    )
    xbmcplugin.setContent(PLUGIN_HANDLE, "movies")
    _add_dir_items(items)


def list_continue_series_versions(tmdb_id, title=""):
    if not _ensure_ready():
        return

    tmdb_id = _normalize_tmdb_id(tmdb_id)
    if not tmdb_id:
        return

    details = _get_tmdb_series_details_cached(tmdb_id) or {}
    series_art = (details.get("art") or {}) if details else {}

    try:
        playback_items = trakt_api.trakt_get_playback("series")
    except Exception:
        playback_items = []

    target_playback = None
    for item in playback_items or []:
        try:
            show = item.get("show") or {}
            ids = show.get("ids") or {}
            progress = _safe_float(item.get("progress"), 0.0)
            if str(ids.get("tmdb") or "") == str(tmdb_id) and 0.0 < progress < 98.0:
                target_playback = item
                break
        except Exception:
            pass

    if not target_playback:
        _add_dir_items([])
        return

    show = target_playback.get("show") or {}
    if not title:
        title = show.get("title") or details.get("title") or "Continue Watching"

    episode = target_playback.get("episode") or {}
    season_num = str(episode.get("season") or "")
    episode_num = str(episode.get("number") or "")
    progress = _safe_float(target_playback.get("progress"), 0.0)

    if not season_num or not episode_num:
        _add_dir_items([])
        return

    matches = _find_all_index_matches("series", title=title, tmdb_id=tmdb_id)
    items = []

    for entry in matches:
        try:
            series_id = entry.get("id") or entry.get("series_id") or ""
            if not series_id:
                continue

            series_info = cache_handler.get(
                "series_info", f"{STATE.username}_{series_id}"
            )
            if not series_info:
                series_info = xtream_api.series_info_by_id(series_id)

            if not isinstance(series_info, dict):
                continue

            episodes_map = series_info.get("episodes", {}) or {}
            season_eps = episodes_map.get(str(season_num), []) or episodes_map.get(
                int(season_num), []
            )

            found_episode = next(
                (
                    ep
                    for ep in season_eps
                    if str(ep.get("episode_num", "")) == str(episode_num)
                ),
                None,
            )
            if not found_episode:
                continue

            stream_id = found_episode.get("id")
            ext = found_episode.get("container_extension", "mp4")
            play_url = xtream_api.build_stream_url(
                stream_id=stream_id,
                stream_type="series",
                container_extension=ext,
            )
            if not play_url:
                continue

            server_episode_title = (
                found_episode.get("title")
                or (found_episode.get("info") or {}).get("title")
                or "Episode {}".format(episode_num)
            )
            display_title = "S{:02d}E{:02d} - {}".format(
                int(season_num), int(episode_num), server_episode_title
            )

            tmdb_ep_details = (
                _get_tmdb_episode_details_cached(
                    tmdb_id, int(season_num), int(episode_num)
                )
                or {}
            )
            ep_art = tmdb_ep_details.get("art") or {}
            season_data = (
                _get_tmdb_season_details_cached(tmdb_id, int(season_num)) or {}
            )
            season_art = season_data.get("art") or {}

            thumb = (
                ep_art.get("thumb")
                or ep_art.get("still")
                or season_art.get("poster")
                or series_art.get("poster")
                or found_episode.get("movie_image")
                or found_episode.get("thumbnail")
                or ""
            )
            if thumb and str(thumb).startswith("/"):
                thumb = "https://image.tmdb.org/t/p/original{}".format(thumb)

            poster = season_art.get("poster") or series_art.get("poster") or thumb
            fanart = (
                ep_art.get("fanart")
                or season_art.get("fanart")
                or series_art.get("fanart")
                or poster
            )
            icon = thumb or poster

            plot_value = tmdb_ep_details.get("overview") or ""
            rating_value = tmdb_ep_details.get("vote_average") or 0
            air_date = tmdb_ep_details.get("air_date") or ""
            year_value = (
                air_date[:4] if len(air_date) >= 4 and air_date[:4].isdigit() else "0"
            )

            li = xbmcgui.ListItem(
                label=_label_with_marker(
                    "{} [COLOR grey]({})[/COLOR]".format(
                        display_title, entry.get("category_name", "TV Series")
                    ),
                    progress=progress,
                )
            )
            li.setArt(_build_art(thumb=thumb, poster=poster, fanart=fanart, icon=icon))
            li.setProperty("IsPlayable", "true")

            tag = li.getVideoInfoTag()
            tag.setTitle(server_episode_title)
            tag.setTvShowTitle(entry.get("title") or entry.get("name") or title or "")
            tag.setSeason(int(season_num))
            tag.setEpisode(int(episode_num))
            tag.setMediaType("episode")
            tag.setPlot(plot_value)
            try:
                if rating_value:
                    tag.setRating(float(rating_value), 10)
            except Exception:
                pass
            if air_date:
                try:
                    tag.setFirstAired(air_date)
                except Exception:
                    pass
            try:
                if year_value and str(year_value).isdigit():
                    tag.setYear(int(year_value))
            except Exception:
                pass
            if tmdb_id:
                try:
                    tag.setUniqueIDs({"tmdb": str(tmdb_id)}, "tmdb")
                except Exception:
                    pass
                li.setProperty("tmdbnumber", str(tmdb_id))
                li.setProperty("season", str(season_num))
                li.setProperty("episode", str(episode_num))

            metadata = {
                "thumb": thumb,
                "poster": poster,
                "fanart": fanart,
                "icon": icon,
                "plot": plot_value,
                "rating": rating_value,
                "year": year_value,
                "tmdb_id": str(tmdb_id),
                "stream_type": "series",
                "stream_id": str(stream_id or ""),
                "season": str(season_num),
                "episode": str(episode_num),
            }

            url = _plugin_url(
                mode="play_stream",
                url=play_url,
                name=display_title,
                meta=_encode_meta(metadata),
            )

            menu_url = _build_stream_menu_url(
                item_id=str(stream_id or ""),
                name=display_title,
                play_url=play_url,
                stream_type="series",
                thumb=thumb,
                poster=poster,
                fanart=fanart,
                icon=icon,
                plot=plot_value,
                rating=str(rating_value or "0"),
                year=str(year_value or "0"),
                tmdb_id=str(tmdb_id),
                season=str(season_num),
                episode=str(episode_num),
                favourite_kind="playable",
                target_mode="play_stream",
                series_id=str(series_id),
                series_name=entry.get("title") or entry.get("name") or title,
                season_num=str(season_num),
            )
            _add_giptv_context_menu(li, menu_url)
            items.append((url, li, False))

        except Exception as e:
            giptv.log(
                "[CONTINUE SERIES VERSIONS] row failed: {}".format(e), xbmc.LOGWARNING
            )

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, title or "Continue Watching")
    xbmcplugin.setContent(PLUGIN_HANDLE, "episodes")
    _add_dir_items(items)


# ---------------------------------------------------------------------------
# EPG helpers
# ---------------------------------------------------------------------------


def _build_live_plot(now_data, next_data, epg_offset_minutes):
    title, desc, start_ts, end_ts = now_data
    duration = max(0, end_ts - start_ts)

    display_start_ts = _apply_offset_minutes(start_ts, -epg_offset_minutes)
    display_end_ts = _apply_offset_minutes(end_ts, -epg_offset_minutes)

    pct = _epg_progress(display_start_ts, display_end_ts)
    bar = _progress_bar(pct)

    short_desc = (desc or "").strip()
    if len(short_desc) > 180:
        short_desc = short_desc[:180] + "..."

    plot_lines = [
        f"[COLOR yellow][B]Now: {title}[/B][/COLOR] "
        f"[COLOR grey][I]{_fmt_time(display_start_ts)} – {_fmt_time(display_end_ts)}[/I][/COLOR]",
        f"[COLOR green]{bar}  {pct}%[/COLOR]",
    ]
    if short_desc:
        plot_lines.append(f"[COLOR white]{short_desc}[/COLOR]")
    if next_data:
        next_title, _, next_start, next_end = next_data
        display_next_start = _apply_offset_minutes(next_start, -epg_offset_minutes)
        display_next_end = _apply_offset_minutes(next_end, -epg_offset_minutes)
        plot_lines.append(
            f"[COLOR yellow][B]Next: {next_title}[/B][/COLOR] "
            f"[COLOR grey][I]{_fmt_time(display_next_start)} – {_fmt_time(display_next_end)}[/I][/COLOR]"
        )

    return title, "\n".join(plot_lines), duration


def _load_xmltv_index_with_retry(retries=3, delay_ms=300):
    for attempt in range(retries):
        index = get_xmltv_index() or {}
        if index:
            giptv.log(
                f"[EPG] XMLTV index loaded on attempt {attempt + 1} with {len(index)} channels",
                xbmc.LOGINFO,
            )
            return index
        giptv.log(
            f"[EPG] XMLTV index empty on attempt {attempt + 1}, retrying...",
            xbmc.LOGWARNING,
        )
        xbmc.sleep(delay_ms)
    giptv.log("[EPG] XMLTV index still empty after retries", xbmc.LOGWARNING)
    return {}


# ---------------------------------------------------------------------------
# Root menu
# ---------------------------------------------------------------------------


def root_menu():
    if not _ensure_ready():
        return

    items = []

    for label, icon, mode_params in [
        (
            "[B][COLOR gold]Favourites[/COLOR][/B]",
            FAVOURITES_ICON,
            {"mode": "favourites"},
        ),
        (
            "[B][COLOR orange]Recently Watched[/COLOR][/B]",
            WATCHED_ICON,
            {"mode": "recently_watched"},
        ),
        (
            "[B][COLOR deepskyblue]Live TV Guide[/COLOR][/B]",
            LIVE_ICON,
            {"mode": "live_guide"},
        ),
    ]:
        li = xbmcgui.ListItem(label)
        li.setArt({"icon": icon, "thumb": icon, "fanart": icon})
        items.append((_plugin_url(**mode_params), li, True))

    for label, stream_type, thumb in [
        ("[B]Live TV[/B]", "live", LIVE_ICON),
        ("[B]Movies[/B]", "vod", MOVIE_ICON),
        ("[B]TV Series[/B]", "series", SERIES_ICON),
    ]:
        li = xbmcgui.ListItem(label=label)
        li.setArt({"thumb": thumb, "icon": thumb, "fanart": thumb})
        li.addContextMenuItems(
            [
                (
                    "GIPTV Menu",
                    f"RunPlugin(plugin://{ADDON_ID}/?action=open_tools_window)",
                )
            ]
        )
        items.append(
            (
                _plugin_url(mode="list_categories", stream_type=stream_type, page="1"),
                li,
                True,
            )
        )

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, "Xtream Content Streams")
    xbmcplugin.setContent(PLUGIN_HANDLE, "videos")
    _add_dir_items(items)
    _log_memory_caches("after root_menu")
    try:
        del items
    except Exception:
        pass
    _trim_route_memory(is_live=False)


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------


def list_categories(stream_type, search_query=None, page=1):
    if not _ensure_ready():
        return

    if search_query is None:
        raw_params = (
            sys.argv[2][1:]
            if len(sys.argv) > 2 and sys.argv[2].startswith("?")
            else sys.argv[2]
        )
        params = dict(urlparse.parse_qsl(raw_params))
        search_query = params.get("search") or params.get("search_query")

    search_query = _normalize_search_query(search_query)
    page = max(1, _safe_int(page, 1))
    items = []

    if not search_query and page == 1:
        if stream_type == "vod":
            for (
                tmdb_id,
                match_list,
                resume_data,
            ) in _get_continue_watching_movie_items():
                try:
                    row = _make_continue_movie_item(tmdb_id, match_list, resume_data)
                    if row:
                        items.append(row)
                except Exception as e:
                    giptv.log(
                        "[CONTINUE MOVIES] row failed: {}".format(e), xbmc.LOGWARNING
                    )

        elif stream_type == "series":
            for (
                tmdb_id,
                match_list,
                playback_item,
            ) in _get_continue_watching_series_items():
                try:
                    row = _make_continue_series_item(tmdb_id, match_list, playback_item)
                    if row:
                        items.append(row)
                except Exception as e:
                    giptv.log(
                        "[CONTINUE SERIES] row failed: {}".format(e), xbmc.LOGWARNING
                    )

    category_list = _safe_category_list(stream_type)
    if category_list is None:
        _notify_and_open_settings("Xtream server/category response invalid")
        return

    if not isinstance(category_list, list):
        _notify_and_open_settings("Xtream categories invalid")
        return

    if search_query:
        category_list = [
            c
            for c in category_list
            if search_query in (c.get("category_name", "") or "").lower()
        ]

    from resources.lib.manager import sort_manager

    sort_mode = sort_manager.get_current_sort("categories", stream_type)
    category_list = _sort_categories(category_list, sort_mode)

    next_mode = "list_series_streams" if stream_type == "series" else "list_streams"
    page_items, has_next, page = _paginate_items(category_list, page)

    if page > 1:
        items.append(
            _prev_page_item(
                "list_categories",
                page,
                stream_type=stream_type,
                search_query=search_query or "",
            )
        )

    for category in page_items:
        try:
            category_name = category.get("category_name", "Unknown Category")
            category_id = category.get("category_id")

            li = xbmcgui.ListItem(label=category_name)
            li.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
            _add_giptv_context_menu(
                li, _build_category_menu_url(stream_type, category_id, category_name)
            )

            items.append(
                (
                    _plugin_url(
                        mode=next_mode,
                        stream_type=stream_type,
                        category_id=category_id,
                        name=category_name,
                        page="1",
                    ),
                    li,
                    True,
                )
            )
        except Exception as e:
            giptv.log("[NAV] category row failed: {}".format(e), xbmc.LOGWARNING)

    if has_next:
        items.append(
            _next_page_item(
                "list_categories",
                page,
                stream_type=stream_type,
                search_query=search_query or "",
            )
        )

    _add_dir_items(items)
    _log_memory_caches("after list_categories")
    try:
        del items, category_list, page_items
    except Exception:
        pass
    _trim_route_memory(is_live=False)


# ---------------------------------------------------------------------------
# list_streams
# ---------------------------------------------------------------------------


def list_streams(stream_type, category_id, name, search_query=None, page=1):
    if not _ensure_ready():
        return

    search_query = _normalize_search_query(search_query)
    page = max(1, _safe_int(page, 1))
    items = []

    stream_list = _safe_stream_list(stream_type, category_id)
    if stream_list is None:
        _notify_and_go_home("Xtream stream response invalid")
        return

    if not isinstance(stream_list, list):
        _notify_and_go_home("Xtream stream data invalid")
        return

    if search_query:
        stream_list = [s for s in stream_list if _stream_matches_query(s, search_query)]

    if stream_type != "live":
        _store_current_items(stream_type, category_id, stream_list)
    else:
        _current_items.set(f"{stream_type}_{category_id}", [])

    is_live = stream_type == "live"
    is_vod = stream_type == "vod"

    xbmcplugin.setContent(PLUGIN_HANDLE, "movies" if is_vod else "videos")

    epg_offset_minutes = settings.get_epg_offset(ADDON) if is_live else 0
    xmltv_index = {}

    movie_resume_map = {}
    watched_movie_ids = set()

    if is_vod and _is_trakt_ready():
        # Parallel fetch of both Trakt data sources
        movie_resume_map, watched_movie_ids = _fetch_trakt_vod_data()

    if is_live:
        catchup_ids = []
        for stream in stream_list:
            try:
                has_catchup = (
                    str(stream.get("tv_archive", stream.get("has_archive", "0"))) == "1"
                )
                if has_catchup:
                    cid = _resolve_xmltv_channel_id_cached(stream)
                    if cid:
                        catchup_ids.append(cid)
            except Exception:
                pass
        set_catchup_channels(catchup_ids)

        start = time.time()
        xmltv_index = _load_xmltv_index_with_retry(retries=4, delay_ms=400)
        giptv.log(f"EPG load took {time.time() - start:.3f}s", xbmc.LOGINFO)

    from resources.lib.manager import sort_manager

    sort_dir_id = f"{stream_type}:{category_id}"
    sort_mode = sort_manager.get_current_sort("streams", sort_dir_id)
    sort_label = sort_manager.get_sort_label("streams", sort_dir_id)
    stream_list = _sort_streams(stream_list, sort_mode)

    page_streams, has_next, page = _paginate_items(stream_list, page)

    if page > 1:
        items.append(
            _prev_page_item(
                "list_streams",
                page,
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=search_query or "",
            )
        )

    for stream in page_streams:
        stream_id = str(
            stream.get("stream_id")
            or stream.get("movie_id")
            or stream.get("vod_id")
            or ""
        )
        if not stream_id:
            continue

        stream_name = (
            stream.get("name")
            or stream.get("title")
            or stream.get("stream_display_name")
            or "Unknown Stream"
        )
        stream_icon = _get_picon_cached(
            stream_id, stream.get("stream_icon"), stream.get("category_id")
        )

        list_item = xbmcgui.ListItem(label=stream_name)
        art_dict = {}
        ext = stream.get("container_extension", "mp4")
        stream_type_for_api = "live"

        plot_value = ""
        rating_value = 0
        year_value = 0
        tmdb_id_value = ""
        channel_id_value = ""
        stream_type_value = "vod" if is_vod else "live"

        if is_vod:
            stream_type_for_api = "vod"
            info_data = stream.get("info", {}) or {}

            raw_tmdb_id = (
                stream.get("tmdb")
                or stream.get("tmdb_id")
                or info_data.get("tmdb")
                or info_data.get("tmdb_id")
            )
            tmdb_id = _normalize_tmdb_id(raw_tmdb_id)

            if not tmdb_id:
                release_date = stream.get("release_date") or ""
                year_hint = ""
                if "-" in release_date:
                    year_part = release_date.split("-")[0]
                    if year_part.isdigit():
                        year_hint = year_part
                elif len(release_date) == 4 and release_date.isdigit():
                    year_hint = release_date
                tmdb_id = _resolve_movie_tmdb_id_cached(stream_name, year_hint)

            tmdb_details = _get_tmdb_movie_details_cached(tmdb_id) if tmdb_id else None

            if tmdb_details:
                art_raw = tmdb_details.get("art", {}) or {}
                art_dict = _build_art(
                    thumb=art_raw.get("thumb", ""),
                    poster=art_raw.get("poster", "") or stream_icon,
                    fanart=art_raw.get("fanart", ""),
                    icon=art_raw.get("icon", "") or stream_icon,
                    fallback=stream_icon or "DefaultVideo.png",
                )
                if tmdb_id:
                    list_item.setProperty("tmdbnumber", tmdb_id)
                    list_item.setProperty("imdbnumber", tmdb_id)

                tag = list_item.getVideoInfoTag()
                tag.setTitle(tmdb_details.get("title") or stream_name)
                tag.setPlot(tmdb_details.get("plot") or "")
                tag.setMediaType("movie")
                if tmdb_details.get("year") and str(tmdb_details["year"]).isdigit():
                    tag.setYear(int(tmdb_details["year"]))
                try:
                    if tmdb_details.get("rating") is not None:
                        tag.setRating(float(tmdb_details["rating"]), 10)
                except Exception:
                    pass
                try:
                    if tmdb_details.get("duration") is not None:
                        tag.setDuration(int(tmdb_details["duration"]))
                    elif info_data.get("duration_secs"):
                        tag.setDuration(int(info_data["duration_secs"]))
                except Exception:
                    pass

                plot_value = tmdb_details.get("plot") or ""
                rating_value = tmdb_details.get("rating") or 0
                year_value = (
                    int(tmdb_details["year"])
                    if tmdb_details.get("year") and str(tmdb_details["year"]).isdigit()
                    else 0
                )
                tmdb_id_value = _normalize_tmdb_id(
                    tmdb_details.get("tmdb_id") or tmdb_id
                )

            else:
                movie_plot = (
                    stream.get("plot")
                    or info_data.get("plot")
                    or "No description available."
                )
                duration = 0
                try:
                    if info_data.get("duration_secs"):
                        duration = int(info_data["duration_secs"])
                except Exception:
                    pass

                year = 0
                release_date = stream.get("release_date") or ""
                if "-" in release_date:
                    year_part = release_date.split("-")[0]
                    if year_part.isdigit():
                        year = int(year_part)
                elif len(release_date) == 4 and release_date.isdigit():
                    year = int(release_date)

                tag = list_item.getVideoInfoTag()
                tag.setTitle(stream_name)
                tag.setPlot(movie_plot)
                tag.setMediaType("movie")
                if duration > 0:
                    tag.setDuration(duration)
                if year > 0:
                    tag.setYear(year)

                art_dict = _build_art(
                    thumb=stream_icon,
                    poster=stream_icon,
                    fanart=stream_icon,
                    icon=stream_icon,
                    fallback="DefaultVideo.png",
                )
                plot_value = movie_plot
                year_value = year
                tmdb_id_value = _normalize_tmdb_id(raw_tmdb_id or tmdb_id)

            resolved_tmdb_id = str(tmdb_id_value or tmdb_id or "")
            watched_flag = (
                resolved_tmdb_id in watched_movie_ids if resolved_tmdb_id else False
            )
            progress_value = None
            if resolved_tmdb_id:
                resume_info = movie_resume_map.get(resolved_tmdb_id) or {}
                if resume_info:
                    progress_value = resume_info.get("progress")

            if watched_flag:
                list_item.setProperty("playcount", "1")
                try:
                    list_item.getVideoInfoTag().setPlaycount(1)
                except Exception:
                    pass

            list_item.setLabel(
                _label_with_marker(
                    stream_name, watched=watched_flag, progress=progress_value
                )
            )

        else:
            stream_type_for_api = "live"
            ext = stream.get("container_extension", "ts")

            selected_format = settings.get_stream_format(ADDON)
            if selected_format == "ts":
                ext = "ts"
            elif selected_format == "m3u8":
                ext = "m3u8"

            art_dict = _build_art(
                thumb=stream_icon,
                poster=stream_icon,
                fanart=stream_icon,
                icon=stream_icon,
                fallback="DefaultVideo.png",
            )
            channel_id = _resolve_xmltv_channel_id_cached(stream)
            channel_id_value = channel_id or ""

            data = (
                get_now_next(xmltv_index, channel_id, epg_offset_minutes)
                if channel_id
                else None
            )
            tag = list_item.getVideoInfoTag()

            if data and data.get("now"):
                title, plot, duration = _build_live_plot(
                    data["now"], data.get("next"), epg_offset_minutes
                )
                list_item.setLabel(f"[COLOR green][LIVE][/COLOR] {stream_name}")
                tag.setTitle(title)
                tag.setPlot(plot)
                tag.setDuration(duration)
                tag.setMediaType("video")
                list_item.setProperty("IsLive", "true")
                plot_value = plot
            else:
                tag.setTitle(stream_name)
                tag.setPlot(stream_name)
                tag.setMediaType("video")
                plot_value = stream_name

        play_url = xtream_api.build_stream_url(
            stream_id=stream_id,
            stream_type=stream_type_for_api,
            container_extension=ext,
        )
        if not play_url:
            continue

        metadata = {
            "thumb": art_dict.get("thumb", ""),
            "poster": art_dict.get("poster", ""),
            "fanart": art_dict.get("fanart", ""),
            "icon": art_dict.get("icon", ""),
            "plot": plot_value,
            "rating": rating_value,
            "year": year_value,
            "tmdb_id": tmdb_id_value,
            "stream_type": stream_type_value,
            "channel_id": channel_id_value,
            "stream_id": stream_id,
        }

        url = _plugin_url(
            mode="play_stream",
            url=play_url,
            name=stream_name,
            meta=_encode_meta(metadata),
        )
        list_item.setProperty("IsPlayable", "true")
        list_item.setArt(art_dict)

        menu_url = None
        if is_live:
            menu_url = _build_stream_menu_url(
                item_id=stream_id,
                name=stream_name,
                play_url=play_url,
                stream_type=stream_type_value,
                thumb=art_dict.get("thumb", ""),
                poster=art_dict.get("poster", ""),
                fanart=art_dict.get("fanart", ""),
                icon=art_dict.get("icon", ""),
                plot=plot_value,
                rating=str(rating_value),
                year=str(year_value),
                tmdb_id=tmdb_id_value,
                channel_id=channel_id_value,
                epg_channel_id=str(stream.get("epg_channel_id", "")),
                has_archive=str(
                    stream.get("tv_archive", stream.get("has_archive", "0"))
                ),
                directory_type="streams",
                directory_id=sort_dir_id,
                refresh_mode="list_streams",
                sort_label=sort_label,
                category_id=category_id,
                category_name=name,
                search_query=search_query or "",
                page=str(page),
                favourite_kind="playable",
                target_mode="play_stream",
            )
        elif is_vod:
            menu_url = _build_stream_menu_url(
                item_id=stream_id,
                name=stream_name,
                play_url=play_url,
                stream_type=stream_type_value,
                thumb=art_dict.get("thumb", ""),
                poster=art_dict.get("poster", ""),
                fanart=art_dict.get("fanart", ""),
                icon=art_dict.get("icon", ""),
                plot=plot_value,
                rating=str(rating_value),
                year=str(year_value),
                tmdb_id=tmdb_id_value,
                directory_type="streams",
                directory_id=sort_dir_id,
                refresh_mode="list_streams",
                sort_label=sort_label,
                category_id=category_id,
                category_name=name,
                search_query=search_query or "",
                page=str(page),
                favourite_kind="playable",
                target_mode="play_stream",
            )

        if menu_url:
            _add_giptv_context_menu(list_item, menu_url)
        items.append((url, list_item, False))

    if has_next:
        items.append(
            _next_page_item(
                "list_streams",
                page,
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=search_query or "",
            )
        )

    _add_dir_items(items)
    _log_memory_caches("after list_streams")
    try:
        del items, stream_list, page_streams, xmltv_index
    except Exception:
        pass
    _trim_route_memory(is_live=is_live)


# ---------------------------------------------------------------------------
# Catchup
# ---------------------------------------------------------------------------


def get_direct_epg_index():
    if not _ensure_ready():
        return {}

    user = (STATE.username or "default").replace("/", "_").replace(":", "_")
    server = (STATE.server or "server").replace("/", "_").replace(":", "_")
    filename = f"epg_index_{user}_{server}.json"
    path = xbmcvfs.translatePath(
        f"special://profile/addon_data/plugin.video.giptv/cache/{filename}"
    )
    if not xbmcvfs.exists(path):
        return {}
    try:
        f = xbmcvfs.File(path, "r")
        raw_data = f.read()
        f.close()
        return json.loads(raw_data).get("index", {})
    except Exception:
        return {}


def list_catchup_dates(stream_id, channel_id, name):
    if not _ensure_ready():
        return

    if channel_id:
        set_catchup_channels([channel_id])

    xmltv_index = get_xmltv_index()
    cid = str(channel_id).strip().upper().replace(" ", "_").replace("-", "_")
    programmes = xmltv_index.get(cid, [])

    items = []
    if not programmes:
        _add_dir_items(items)
        _trim_route_memory(is_live=True)
        return

    now_ts = int(time.time())
    dates = {
        datetime.datetime.fromtimestamp(start_ts).date()
        for start_ts, _, _, _ in programmes
        if start_ts <= now_ts
    }

    for d in sorted(dates, reverse=True):
        li = xbmcgui.ListItem(label=d.strftime("%A %d %B"))
        items.append(
            (
                giptv.build_url(
                    mode="list_catchup_programmes",
                    stream_id=stream_id,
                    channel_id=channel_id,
                    date=d.isoformat(),
                    name=name,
                ),
                li,
                True,
            )
        )

    _add_dir_items(items)
    _trim_route_memory(is_live=True)


def list_catchup_programmes(stream_id, channel_id, date):
    if not _ensure_ready():
        return

    if channel_id:
        set_catchup_channels([channel_id])

    xmltv = get_xmltv_index()
    cid = str(channel_id).strip().upper().replace(" ", "_").replace("-", "_")
    now_ts = int(time.time())
    programmes = xmltv.get(cid, [])
    catchup_offset = settings.get_catchup_offset(ADDON)

    items = []

    for start_ts, end_ts, title, desc in programmes:
        dt = datetime.datetime.fromtimestamp(start_ts)
        if dt.date().isoformat() != date or start_ts > now_ts:
            continue

        duration = int((end_ts - start_ts) / 60)
        adjusted_start_ts = _apply_offset_minutes(start_ts, catchup_offset)
        start_str = datetime.datetime.fromtimestamp(adjusted_start_ts).strftime(
            "%Y-%m-%d:%H-%M"
        )
        label_time = dt.astimezone().strftime("%H:%M")

        final_url = (
            f"{STATE.server.rstrip('/')}/timeshift/"
            f"{STATE.username}/{STATE.password}/"
            f"{duration}/{start_str}/{stream_id}.ts"
        )

        url = giptv.build_url(mode="play_catchup", url=final_url, name=title)
        li = xbmcgui.ListItem(label=f"{label_time} — {title}")
        li.getVideoInfoTag().setPlot(desc)
        li.setProperty("IsPlayable", "true")
        items.append((url, li, False))

    _add_dir_items(items)
    _trim_route_memory(is_live=True)


# ---------------------------------------------------------------------------
# list_series_streams
# ---------------------------------------------------------------------------


def list_series_streams(stream_type, category_id, name, search_query=None, page=1):
    if not _ensure_ready():
        return

    search_query = _normalize_search_query(search_query)
    page = max(1, _safe_int(page, 1))
    items = []

    series_list = _safe_stream_list(stream_type, category_id)
    if series_list is None:
        _notify_and_go_home("Xtream series response invalid")
        return
    if not isinstance(series_list, list):
        _notify_and_go_home("Xtream series data invalid")
        return

    if search_query:
        series_list = [s for s in series_list if _stream_matches_query(s, search_query)]

    from resources.lib.manager import sort_manager

    sort_dir_id = f"{stream_type}:{category_id}"
    sort_mode = sort_manager.get_current_sort("streams", sort_dir_id)
    sort_label = sort_manager.get_sort_label("streams", sort_dir_id)
    series_list = _sort_streams(series_list, sort_mode)

    xbmcplugin.setContent(PLUGIN_HANDLE, "tvshows")
    page_series, has_next, page = _paginate_items(series_list, page)

    # Resolve TMDb IDs first so we can prefetch details + progress in parallel
    def _resolve_series_tmdb(series):
        tmdb_id = _normalize_tmdb_id(_extract_tmdb_id(series))
        if not tmdb_id:
            release_date = series.get("release_date") or ""
            year_str = release_date.split("-")[0] if "-" in release_date else ""
            tmdb_id = _resolve_series_tmdb_id_cached(series.get("name", ""), year_str)
        return tmdb_id

    # Build tmdb_id list for this page
    series_tmdb_ids = []
    for series in page_series:
        series_tmdb_ids.append(_resolve_series_tmdb(series))

    # Prefetch details and show progress in parallel
    unique_ids = list({t for t in series_tmdb_ids if t})
    if unique_ids:
        with ThreadPoolExecutor(max_workers=min(len(unique_ids), 8)) as pool:
            list(pool.map(_get_tmdb_series_details_cached, unique_ids))
            list(pool.map(_get_show_progress_summary_cached, unique_ids))

    if page > 1:
        items.append(
            _prev_page_item(
                "list_series_streams",
                page,
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=search_query or "",
            )
        )

    for series, tmdb_id in zip(page_series, series_tmdb_ids):
        series_name = series.get("name", "Unknown Series")
        series_id = series.get("series_id")
        plot = series.get("plot", "No description available.")
        rating_str = series.get("rating", "0")
        genre = series.get("genre", "")
        cast_str = series.get("cast", "")
        series_icon = series.get("cover", "")

        release_date = series.get("release_date") or ""
        year_str = release_date.split("-")[0] if "-" in release_date else ""
        year = int(year_str) if year_str.isdigit() else 0

        try:
            rating = float(rating_str)
        except Exception:
            rating = 0.0

        cast_list = [c.strip() for c in cast_str.split(",")] if cast_str else []

        show_progress = _get_show_progress_summary_cached(tmdb_id) if tmdb_id else {}
        watched_flag = bool(show_progress.get("completed"))
        progress_value = None

        aired_total = int(show_progress.get("aired") or 0)
        completed_total = int(show_progress.get("completed_count") or 0)
        if aired_total > 0 and completed_total > 0 and not watched_flag:
            try:
                progress_value = int(
                    (float(completed_total) / float(aired_total)) * 100.0
                )
            except Exception:
                pass

        details = _get_tmdb_series_details_cached(tmdb_id) if tmdb_id else None
        detail_art = (details or {}).get("art") or {}

        if detail_art.get("poster"):
            series_icon = detail_art.get("poster")
        if details:
            if details.get("plot"):
                plot = details["plot"]
            if details.get("rating") is not None:
                try:
                    rating = float(details["rating"] or 0.0)
                except Exception:
                    pass
            genre_list = details.get("genre") or []
            if genre_list:
                genre = ", ".join(genre_list)
            cast_data = details.get("cast") or []
            if cast_data:
                cast_list = [c.get("name") for c in cast_data if c.get("name")]

        art_dict = _build_art(
            thumb=detail_art.get("thumb", ""),
            poster=detail_art.get("poster", "") or series_icon or "",
            fanart=detail_art.get("fanart", ""),
            icon=detail_art.get("thumb", "")
            or detail_art.get("poster", "")
            or series_icon
            or "",
            fallback="DefaultTVShows.png",
        )

        li = xbmcgui.ListItem(
            label=_label_with_marker(
                series_name, watched=watched_flag, progress=progress_value
            )
        )
        li.setArt(art_dict)

        tag = li.getVideoInfoTag()
        tag.setTitle(series_name)
        tag.setPlot(plot)
        if genre:
            tag.setGenres(
                [g.strip() for g in str(genre).split(",") if g.strip()]
                if isinstance(genre, str)
                else genre
            )
        tag.setYear(year)
        tag.setMediaType("tvshow")
        tag.setRating(rating, 10)
        tag.setCast([xbmc.Actor(actor) for actor in cast_list if actor])

        if watched_flag:
            li.setProperty("playcount", "1")
            try:
                tag.setPlaycount(1)
            except Exception:
                pass

        if tmdb_id:
            tag.setUniqueIDs({"tmdb": str(tmdb_id)}, "tmdb")
            li.setProperty("imdbnumber", str(tmdb_id))

        menu_url = _build_stream_menu_url(
            item_id=str(series_id),
            name=series_name,
            play_url="",
            stream_type="series",
            thumb=art_dict.get("thumb", ""),
            poster=art_dict.get("poster", ""),
            fanart=art_dict.get("fanart", ""),
            icon=art_dict.get("icon", ""),
            plot=plot,
            rating=str(rating),
            year=str(year),
            tmdb_id=str(tmdb_id or ""),
            directory_type="streams",
            directory_id=sort_dir_id,
            refresh_mode="list_series_streams",
            sort_label=sort_label,
            category_id=category_id,
            category_name=name,
            search_query=search_query or "",
            page=str(page),
            favourite_kind="series_folder",
            target_mode="list_series_seasons",
            series_id=str(series_id or ""),
            series_name=series_name,
        )
        _add_giptv_context_menu(li, menu_url)
        items.append(
            (
                _plugin_url(
                    mode="list_series_seasons",
                    series_id=series_id,
                    series_name=series_name,
                ),
                li,
                True,
            )
        )

    if has_next:
        items.append(
            _next_page_item(
                "list_series_streams",
                page,
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=search_query or "",
            )
        )

    _add_dir_items(items)
    _log_memory_caches("after list_series_streams")
    try:
        del items, series_list, page_series
    except Exception:
        pass
    _trim_route_memory(is_live=False)


# ---------------------------------------------------------------------------
# list_series_seasons
# ---------------------------------------------------------------------------


def list_series_seasons(series_id, series_name):
    if not _ensure_ready():
        return

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, series_name)
    xbmcplugin.setContent(PLUGIN_HANDLE, "videos")

    series_info_response = cache_handler.get(
        "series_info", f"{STATE.username}_{series_id}"
    )
    if not series_info_response:
        series_info_response = xtream_api.series_info_by_id(series_id)

    if not isinstance(series_info_response, dict):
        _notify_and_go_home("Series details unavailable")
        return

    if "episodes" not in series_info_response:
        _notify_and_go_home("Series episode data unavailable")
        return

    episodes_by_season = series_info_response.get("episodes", {})
    if not episodes_by_season:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            f"No seasons or episodes found for {series_name}.",
            icon="INFO",
        )
        return

    series_info = series_info_response.get(
        "info", series_info_response.get("series_info", {})
    )
    tmdb_id = _normalize_tmdb_id(_extract_tmdb_id(series_info_response))
    if not tmdb_id:
        release_date = (
            series_info.get("releaseDate") or series_info.get("release_date") or ""
        )
        year_hint = release_date[:4] if release_date[:4].isdigit() else ""
        tmdb_id = _resolve_series_tmdb_id_cached(series_name, year_hint)

    show_progress = _get_show_progress_summary_cached(tmdb_id) if tmdb_id else {}
    season_progress_map = show_progress.get("season_map") or {}

    tmdb_series_details = _get_tmdb_series_details_cached(tmdb_id) if tmdb_id else None
    detail_art = (tmdb_series_details or {}).get("art") or {}

    series_poster = (
        detail_art.get("poster")
        or series_info_response.get("cover")
        or series_info.get("cover", "")
    )
    series_fanart = detail_art.get("fanart") or ""

    # Prefetch season details in parallel
    season_nums = list(episodes_by_season.keys())
    if tmdb_id:
        with ThreadPoolExecutor(max_workers=min(len(season_nums), 6)) as pool:
            list(
                pool.map(
                    lambda s: _get_tmdb_season_details_cached(tmdb_id, int(s)),
                    season_nums,
                )
            )

    items = []

    for season_num in sorted(season_nums, key=int):
        season_title = f"Season {season_num}"
        season_data = (
            _get_tmdb_season_details_cached(tmdb_id, int(season_num))
            if tmdb_id
            else None
        )
        season_art = (season_data or {}).get("art") or {}
        season_plot = (season_data or {}).get("overview") or series_info.get("plot", "")
        season_rating = (season_data or {}).get("vote_average") or series_info.get(
            "rating", "0"
        )

        watched_flag = False
        progress_value = None
        season_summary = season_progress_map.get(str(season_num)) or {}

        if season_summary:
            watched_flag = bool(season_summary.get("complete"))
            aired_count = int(season_summary.get("aired") or 0)
            completed_count = int(season_summary.get("completed") or 0)
            if aired_count > 0 and completed_count > 0 and not watched_flag:
                try:
                    progress_value = int(
                        (float(completed_count) / float(aired_count)) * 100.0
                    )
                except Exception:
                    pass

        url = _plugin_url(
            mode="list_series_episodes",
            series_id=series_id,
            season_num=season_num,
            series_name=series_name,
            series_poster=series_poster,
            series_fanart=series_fanart,
            tmdb_id=tmdb_id,
        )

        li = xbmcgui.ListItem(
            label=_label_with_marker(
                season_title, watched=watched_flag, progress=progress_value
            )
        )
        art_dict = _build_art(
            thumb=season_art.get("poster", "") or series_poster,
            poster=season_art.get("poster", "") or series_poster,
            fanart=season_art.get("fanart", "") or series_fanart,
            icon=season_art.get("poster", "") or series_poster,
            fallback="DefaultSeason.png",
        )
        li.setArt(art_dict)

        tag = li.getVideoInfoTag()
        tag.setMediaType("season")
        tag.setTitle(season_title)
        tag.setTvShowTitle(series_name)
        tag.setSeason(int(season_num))
        if season_plot:
            tag.setPlot(season_plot)

        air_date = (season_data or {}).get("air_date") or ""
        if air_date:
            try:
                tag.setYear(int(air_date[:4]))
            except Exception:
                pass
        elif series_info.get("releaseDate"):
            try:
                tag.setYear(int(series_info["releaseDate"][:4]))
            except Exception:
                pass

        if watched_flag:
            li.setProperty("playcount", "1")
            try:
                tag.setPlaycount(1)
            except Exception:
                pass

        li.setProperty("tvshow.tmdb_id", str(tmdb_id or ""))
        li.setProperty("season", str(season_num))
        li.setProperty("mediatype", "season")

        custom_menu_url = giptv.build_url(
            action="open_context_window",
            item_id=f"season:{series_id}:{season_num}",
            name=season_title,
            play_url="",
            stream_type="series",
            thumb=art_dict.get("thumb", ""),
            poster=art_dict.get("poster", ""),
            fanart=art_dict.get("fanart", ""),
            icon=art_dict.get("icon", ""),
            plot=season_plot,
            rating=str(season_rating or "0"),
            year="",
            tmdb_id=str(tmdb_id or ""),
            channel_id="",
            epg_channel_id="",
            has_archive="0",
            directory_type="",
            directory_id="",
            refresh_mode="",
            sort_label="",
            category_id="",
            category_name=series_name,
            search_query="",
            page="1",
            season=str(season_num),
            favourite_kind="season_folder",
            target_mode="list_series_episodes",
            series_id=str(series_id or ""),
            series_name=series_name,
            season_num=str(season_num),
        )
        _add_giptv_context_menu(li, custom_menu_url)
        items.append((url, li, True))

    _add_dir_items(items)
    _log_memory_caches("after list_series_seasons")
    try:
        del items, episodes_by_season, series_info_response
    except Exception:
        pass
    _trim_route_memory(is_live=False)


# ---------------------------------------------------------------------------
# list_series_episodes
# ---------------------------------------------------------------------------


def list_series_episodes(
    series_id, season_num, series_name, series_poster="", series_fanart="", tmdb_id=""
):
    if not _ensure_ready():
        return

    raw_params = (
        sys.argv[2][1:]
        if len(sys.argv) > 2 and sys.argv[2].startswith("?")
        else sys.argv[2]
    )
    params = dict(urlparse.parse_qsl(raw_params))
    series_poster = params.get("series_poster", series_poster)
    series_fanart = params.get("series_fanart", series_fanart)
    tmdb_id = params.get("tmdb_id") or tmdb_id

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, f"{series_name} - Season {season_num}")
    xbmcplugin.setContent(PLUGIN_HANDLE, "episodes")

    series_info = cache_handler.get("series_info", f"{STATE.username}_{series_id}")
    if not series_info:
        series_info = xtream_api.series_info_by_id(series_id)

    if not isinstance(series_info, dict):
        _notify_and_go_home("Episode data unavailable")
        return

    episodes = series_info.get("episodes", {}).get(str(season_num), [])
    if not episodes:
        episodes = series_info.get("episodes", {}).get(season_num, [])

    if not episodes:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            f"No episodes found for Season {season_num}.",
            icon="INFO",
        )
        return

    tmdb_series_details = _get_tmdb_series_details_cached(tmdb_id) if tmdb_id else None
    tmdb_series_art = (tmdb_series_details or {}).get("art") or {}

    if tmdb_series_art.get("poster"):
        series_poster = tmdb_series_art["poster"]
    if tmdb_series_art.get("fanart"):
        series_fanart = tmdb_series_art["fanart"]

    season_data = (
        _get_tmdb_season_details_cached(tmdb_id, int(season_num)) if tmdb_id else None
    )
    season_art = (season_data or {}).get("art") or {}

    watched_episode_keys = set()
    episode_resume_map = {}

    if _is_trakt_ready() and tmdb_id:
        # Parallel fetch of watched keys + resume map
        watched_episode_keys, episode_resume_map = _fetch_trakt_episode_data(tmdb_id)

    # Prefetch episode details in parallel
    if tmdb_id:
        ep_nums = []
        for ep in episodes:
            try:
                ep_nums.append(int(ep.get("episode_num", 1)))
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=min(len(ep_nums), 8)) as pool:
            list(
                pool.map(
                    lambda n: _get_tmdb_episode_details_cached(
                        tmdb_id, int(season_num), n
                    ),
                    ep_nums,
                )
            )

    items = []

    for episode in episodes:
        episode_data = episode.get("info")
        if isinstance(episode_data, list):
            episode_data = episode_data[0] if episode_data else {}
        if not isinstance(episode_data, dict):
            episode_data = {}

        episode_num_str = str(episode.get("episode_num", "1"))
        base_title = episode.get("title", f"Episode {episode_num_str}")
        episode_title = (
            f"S{int(season_num):02d}E{int(episode_num_str):02d} - {base_title}"
        )

        stream_id = episode.get("id")
        ext = episode.get("container_extension", "mp4")
        play_url = xtream_api.build_stream_url(
            stream_id=stream_id,
            stream_type="series",
            container_extension=ext,
        )
        if not play_url:
            continue

        watched_flag = (str(season_num), str(episode_num_str)) in watched_episode_keys
        resume_info = (
            episode_resume_map.get((str(season_num), str(episode_num_str))) or {}
        )
        progress_value = resume_info.get("progress") if resume_info else None

        li = xbmcgui.ListItem(
            label=_label_with_marker(
                episode_title, watched=watched_flag, progress=progress_value
            )
        )
        if watched_flag:
            li.setProperty("playcount", "1")
            try:
                li.getVideoInfoTag().setPlaycount(1)
            except Exception:
                pass
        li.setProperty("IsPlayable", "true")

        episode_icon = episode_data.get("movie_image", "") or episode.get(
            "thumbnail", ""
        )
        tmdb_ep_details = (
            _get_tmdb_episode_details_cached(
                tmdb_id, int(season_num), int(episode_num_str)
            )
            if tmdb_id
            else None
        )
        ep_art = (tmdb_ep_details or {}).get("art") or {}

        ep_thumb = (
            ep_art.get("thumb")
            or ep_art.get("still")
            or (tmdb_ep_details or {}).get("still_path")
            or ""
        )
        if ep_thumb and ep_thumb.startswith("/"):
            ep_thumb = "https://image.tmdb.org/t/p/original{}".format(ep_thumb)

        art_dict = _build_art(
            thumb=ep_thumb
            or episode_icon
            or season_art.get("poster", "")
            or series_poster,
            poster=season_art.get("poster", "") or series_poster,
            fanart=ep_art.get("fanart", "")
            or season_art.get("fanart", "")
            or series_fanart,
            icon=ep_thumb
            or episode_icon
            or season_art.get("poster", "")
            or series_poster,
            fallback="DefaultVideo.png",
        )
        li.setArt(art_dict)

        tag = li.getVideoInfoTag()
        tag.setTitle(base_title)
        tag.setTvShowTitle(series_name)
        tag.setSeason(int(season_num))
        tag.setEpisode(int(episode_num_str))
        tag.setMediaType("episode")

        plot_value = ""
        rating_value = 0
        year_value = 0

        if tmdb_ep_details:
            plot_value = tmdb_ep_details.get("overview") or ""
            rating_value = tmdb_ep_details.get("vote_average") or 0
            air_date = tmdb_ep_details.get("air_date") or ""
            if len(air_date) >= 4 and air_date[:4].isdigit():
                year_value = int(air_date[:4])

            tag.setPlot(plot_value)
            try:
                tag.setRating(float(rating_value), 10)
            except Exception:
                pass
            if air_date:
                try:
                    tag.setFirstAired(air_date)
                except Exception:
                    pass
            try:
                if tmdb_ep_details.get("runtime"):
                    tag.setDuration(int(tmdb_ep_details["runtime"]))
            except Exception:
                pass
        else:
            plot_value = episode_data.get("plot", "") or ""
            tag.setPlot(plot_value)

        if tmdb_id:
            tag.setUniqueIDs({"tmdb": str(tmdb_id)}, "tmdb")
            li.setProperty("tmdbnumber", str(tmdb_id))
            li.setProperty("season", str(season_num))
            li.setProperty("episode", str(episode_num_str))

        metadata = {
            "thumb": art_dict.get("thumb", ""),
            "poster": art_dict.get("poster", ""),
            "fanart": art_dict.get("fanart", ""),
            "icon": art_dict.get("icon", ""),
            "plot": plot_value,
            "rating": rating_value,
            "year": year_value,
            "tmdb_id": str(tmdb_id or ""),
            "stream_type": "series",
            "stream_id": str(stream_id or ""),
            "season": str(season_num),
            "episode": str(episode_num_str),
        }

        url = _plugin_url(
            mode="play_stream",
            url=play_url,
            name=episode_title,
            meta=_encode_meta(metadata),
        )

        custom_menu_url = giptv.build_url(
            action="open_context_window",
            item_id=str(stream_id or ""),
            name=episode_title,
            play_url=play_url,
            stream_type="series",
            thumb=art_dict.get("thumb", ""),
            poster=art_dict.get("poster", ""),
            fanart=art_dict.get("fanart", ""),
            icon=art_dict.get("icon", ""),
            plot=plot_value,
            rating=str(rating_value),
            year=str(year_value),
            tmdb_id=str(tmdb_id or ""),
            season=str(season_num),
            episode=str(episode_num_str),
            channel_id="",
            epg_channel_id="",
            has_archive="0",
            directory_type="",
            directory_id="",
            refresh_mode="",
            sort_label="",
            category_id="",
            category_name=series_name,
            search_query="",
            page="1",
            favourite_kind="playable",
            target_mode="play_stream",
            series_id=str(series_id or ""),
            series_name=series_name,
            season_num=str(season_num),
        )
        _add_giptv_context_menu(li, custom_menu_url)
        items.append((url, li, False))

    _add_dir_items(items)
    _log_memory_caches("after list_series_episodes")
    try:
        del items, episodes, series_info
    except Exception:
        pass
    _trim_route_memory(is_live=False)


# ---------------------------------------------------------------------------
# Filter prompts
# ---------------------------------------------------------------------------


def prompt_filter_categories(stream_type):
    if not _ensure_ready():
        return
    category_list = _safe_category_list(stream_type)
    if category_list is None:
        _notify_and_open_settings("Xtream server/category response invalid")
        return
    value = _normalize_search_query(
        _safe_nonempty_text(_show_filter_keyboard("Filter"))
    )
    if not value or not _has_category_matches(category_list, value):
        return
    xbmc.executebuiltin(
        "Container.Update({})".format(
            _plugin_url(
                mode="list_categories",
                stream_type=stream_type,
                search_query=value,
                page="1",
            )
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")


def prompt_filter_streams(stream_type, category_id, name):
    if not _ensure_ready():
        return
    stream_list = _safe_stream_list(stream_type, category_id)
    if stream_list is None:
        _notify_and_go_home("Xtream stream response invalid")
        return
    value = _normalize_search_query(
        _safe_nonempty_text(_show_filter_keyboard("Filter"))
    )
    if not value or not any(_stream_matches_query(s, value) for s in stream_list):
        return
    xbmc.executebuiltin(
        "Container.Update({})".format(
            _plugin_url(
                mode="list_streams",
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=value,
                page="1",
            )
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")


def prompt_filter_series(stream_type, category_id, name):
    if not _ensure_ready():
        return
    series_list = _safe_stream_list(stream_type, category_id)
    if series_list is None:
        _notify_and_go_home("Xtream series response invalid")
        return
    value = _normalize_search_query(
        _safe_nonempty_text(_show_filter_keyboard("Filter"))
    )
    if not value or not any(_stream_matches_query(s, value) for s in series_list):
        return
    xbmc.executebuiltin(
        "Container.Update({})".format(
            _plugin_url(
                mode="list_series_streams",
                stream_type=stream_type,
                category_id=category_id,
                name=name,
                search_query=value,
                page="1",
            )
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")
