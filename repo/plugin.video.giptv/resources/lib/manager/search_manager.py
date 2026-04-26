# -*- coding: utf-8 -*-
try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

import sys
import difflib
import unicodedata
import time

from resources.utils.config import ensure_api_ready
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

from resources.lib.manager.index_manager import _read_index, build_index
import resources.lib.navigator as navigator
import resources.utils.giptv as giptv

ADDON = xbmcaddon.Addon()

if len(sys.argv) > 1 and sys.argv[1].isdigit():
    PLUGIN_HANDLE = int(sys.argv[1])
else:
    PLUGIN_HANDLE = -1

ADDON_ID = ADDON.getAddonInfo("id")

SEARCH_TIMEOUT_SECONDS = 4.0
FUZZY_THRESHOLD = 0.65
MAX_FUZZY_FALLBACK = 120


def _safe_end_of_directory(handle=None):
    handle = PLUGIN_HANDLE if handle is None else handle
    if handle >= 0:
        xbmcplugin.endOfDirectory(handle)


def _normalize_title(value):
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.lower().strip()


def _normalize_query(value):
    return _normalize_title((value or "").strip())


def _get_query(query, heading):
    query = (query or "").strip()
    if query:
        return _normalize_query(query)

    keyboard = xbmc.Keyboard("", heading)
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None

    query = keyboard.getText().strip()
    if not query:
        return None

    return _normalize_query(query)


def _build_plugin_url(**params):
    return sys.argv[0] + "?" + urlparse.urlencode(params)


def _add_directory_item(
    url,
    label,
    is_folder=True,
    art=None,
    info=None,
    properties=None,
):
    if PLUGIN_HANDLE < 0:
        return

    li = xbmcgui.ListItem(label=label)

    if art:
        li.setArt(art)

    if info:
        try:
            li.setInfo("video", info)
        except Exception:
            pass

    if properties:
        for k, v in properties.items():
            try:
                li.setProperty(k, str(v))
            except Exception:
                pass

    xbmcplugin.addDirectoryItem(PLUGIN_HANDLE, url, li, isFolder=is_folder)


def _timed_out(start_time):
    return (time.time() - start_time) > SEARCH_TIMEOUT_SECONDS


def _notify_timeout():
    giptv.notification(
        ADDON.getAddonInfo("name"),
        "Search timed out. Please try again.",
        icon="INFO",
    )


def _prompt_rebuild_index(label):
    return xbmcgui.Dialog().yesno(
        ADDON.getAddonInfo("name"),
        "Search index missing or outdated. Would you like to rebuild right now?\n\nNOTE: May take a few mins depending on your device but worth it!",
    )


def _rebuild_index():
    try:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "Rebuilding search index...",
            icon="INFO",
        )
        build_index(notify=True, source="search_manager_prompt_rebuild", force=True)
    except Exception as e:
        giptv.log("Failed to rebuild index: {}".format(e), xbmc.LOGERROR)
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "Index rebuild failed.",
            icon="ERROR",
        )


def _load_index_or_prompt(index_type, label):
    index_data = _read_index(index_type)
    if index_data:
        return index_data

    if _prompt_rebuild_index(label):
        _rebuild_index()
        index_data = _read_index(index_type)

    return index_data or []


def _entry_search_text(entry):
    return entry.get("search_text") or entry.get("lower") or ""


def _entry_search_tokens(entry):
    return entry.get("search_tokens") or []


def _fast_score(query, entry_text, entry_tokens=None):
    query = _normalize_query(query)
    entry_text = _normalize_query(entry_text)
    entry_tokens = [_normalize_query(t) for t in (entry_tokens or []) if t]

    if not query or not entry_text:
        return 0.0

    if query == entry_text:
        return 1.0

    if query in entry_text:
        return 0.97

    if query in entry_tokens:
        return 0.96

    query_tokens = [t for t in query.split() if t]
    if query_tokens and entry_tokens:
        hits = sum(1 for t in query_tokens if t in entry_tokens)
        if hits:
            token_score = float(hits) / float(len(query_tokens))
            if token_score >= 1.0:
                return 0.95
            if token_score >= 0.75:
                return 0.90
            if token_score >= 0.5:
                return 0.82

    return 0.0


def _rank_matches(query, index, threshold=FUZZY_THRESHOLD, limit=20, start_time=None):
    primary = []
    fallback = []

    q = _normalize_query(query)

    for entry in index:
        if start_time and _timed_out(start_time):
            return None

        text = _entry_search_text(entry)
        tokens = _entry_search_tokens(entry)

        if not text:
            continue

        score = _fast_score(q, text, tokens)
        if score > 0.0:
            primary.append((entry, score))
        else:
            fallback.append(entry)

    fallback = fallback[:MAX_FUZZY_FALLBACK]

    for entry in fallback:
        if start_time and _timed_out(start_time):
            return None

        text = _entry_search_text(entry)
        if not text:
            continue

        score = difflib.SequenceMatcher(None, q, _normalize_query(text)).ratio()
        if score >= threshold:
            primary.append((entry, score))

    primary.sort(key=lambda x: x[1], reverse=True)
    return primary[:limit]


def global_vod_search(query=None):
    if not ensure_api_ready():
        return

    query = _get_query(query, "Search ALL Movies")
    if not query:
        return

    start_time = time.time()
    vod_index = _load_index_or_prompt("vod", "Movies")
    if not vod_index:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No VOD index found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    if _timed_out(start_time):
        _notify_timeout()
        _safe_end_of_directory()
        return

    if PLUGIN_HANDLE >= 0:
        xbmcplugin.setPluginCategory(
            PLUGIN_HANDLE, "Global Movie Search: {}".format(query)
        )
        xbmcplugin.setContent(PLUGIN_HANDLE, "movies")

    matches = _rank_matches(query, vod_index, limit=30, start_time=start_time)
    if matches is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    if not matches:
        if _prompt_rebuild_index("Movies"):
            _rebuild_index()
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No matching movies found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    seen_categories = set()
    count = 0

    for entry, _ in matches:
        category_id = entry.get("category_id", "")
        category_name = entry.get("category_name", "Unknown Category")

        if category_id in seen_categories:
            continue
        seen_categories.add(category_id)

        url = _build_plugin_url(
            mode="list_streams",
            stream_type="vod",
            category_id=category_id,
            name=category_name,
            search_query=query,
            page="1",
        )

        _add_directory_item(url, category_name, is_folder=True)

        count += 1
        if count >= 5:
            break

    _safe_end_of_directory()


def global_live_search(query=None):
    if not ensure_api_ready():
        return

    query = _get_query(query, "Search ALL Live TV")
    if not query:
        return

    start_time = time.time()
    live_index = _load_index_or_prompt("live", "Live TV")
    if not live_index:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No Live index found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    if _timed_out(start_time):
        _notify_timeout()
        _safe_end_of_directory()
        return

    if PLUGIN_HANDLE >= 0:
        xbmcplugin.setPluginCategory(
            PLUGIN_HANDLE, "Global Live Search: {}".format(query)
        )
        xbmcplugin.setContent(PLUGIN_HANDLE, "videos")

    matches = _rank_matches(query, live_index, limit=30, start_time=start_time)
    if matches is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    if not matches:
        if _prompt_rebuild_index("Live TV"):
            _rebuild_index()
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No matching channels found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    seen_categories = set()
    count = 0

    for entry, _ in matches:
        category_id = entry.get("category_id", "")
        category_name = entry.get("category_name", "Unknown Category")

        if category_id in seen_categories:
            continue
        seen_categories.add(category_id)

        url = _build_plugin_url(
            mode="list_streams",
            stream_type="live",
            category_id=category_id,
            name=category_name,
            search_query=query,
            page="1",
        )

        _add_directory_item(url, category_name, is_folder=True)

        count += 1
        if count >= 5:
            break

    _safe_end_of_directory()


def global_series_search(query=None):
    if not ensure_api_ready():
        return

    query = _get_query(query, "Search ALL TV Series")
    if not query:
        return

    start_time = time.time()
    series_index = _load_index_or_prompt("series", "TV Series")
    if not series_index:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No Series index found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    if _timed_out(start_time):
        _notify_timeout()
        _safe_end_of_directory()
        return

    if PLUGIN_HANDLE >= 0:
        xbmcplugin.setPluginCategory(
            PLUGIN_HANDLE, "Global Series Search: {}".format(query)
        )
        xbmcplugin.setContent(PLUGIN_HANDLE, "tvshows")

    matches = _rank_matches(query, series_index, limit=10, start_time=start_time)
    if matches is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    if not matches:
        if _prompt_rebuild_index("TV Series"):
            _rebuild_index()
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No matching series found.",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    top_series = [entry for entry, _ in matches[:5]]

    for entry in top_series:
        series_id = entry.get("id")
        title = entry.get("title") or "Unknown Series"
        thumb = entry.get("thumb") or ""
        tmdb_id = entry.get("tmdb")

        url = _build_plugin_url(
            mode="list_series_seasons",
            series_id=series_id,
            series_name=title,
        )

        art = {"thumb": thumb, "poster": thumb} if thumb else None
        info = {"title": title, "mediatype": "tvshow"}
        props = {}
        if tmdb_id:
            props["tmdbnumber"] = str(tmdb_id)
            props["imdbnumber"] = str(tmdb_id)

        _add_directory_item(
            url,
            title,
            is_folder=True,
            art=art,
            info=info,
            properties=props,
        )

    _safe_end_of_directory()


def global_search(query=None):
    if not ensure_api_ready():
        return

    query = _get_query(query, "Global Search (Live / Movies / Series)")
    if not query:
        return

    start_time = time.time()

    live_index = _load_index_or_prompt("live", "Live TV")
    vod_index = _load_index_or_prompt("vod", "Movies")
    series_index = _load_index_or_prompt("series", "TV Series")

    if not (live_index or vod_index or series_index):
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No search index found.",
            icon="ERROR",
        )
        _safe_end_of_directory()
        return

    if _timed_out(start_time):
        _notify_timeout()
        _safe_end_of_directory()
        return

    if PLUGIN_HANDLE >= 0:
        xbmcplugin.setPluginCategory(PLUGIN_HANDLE, "Global Search: {}".format(query))
        xbmcplugin.setContent(PLUGIN_HANDLE, "videos")

    def add_category_items(matches, stream_type, max_items=2):
        seen_categories = set()
        count = 0

        for entry, _ in matches:
            category_id = entry.get("category_id", "")
            category_name = entry.get("category_name", "Unknown Category")

            if category_id in seen_categories:
                continue
            seen_categories.add(category_id)

            url = _build_plugin_url(
                mode="list_streams",
                stream_type=stream_type,
                category_id=category_id,
                name=category_name,
                search_query=query,
                page="1",
            )

            _add_directory_item(url, category_name, is_folder=True)

            count += 1
            if count >= max_items:
                break

    top_live = _rank_matches(query, live_index, limit=10, start_time=start_time)
    if top_live is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    top_vod = _rank_matches(query, vod_index, limit=10, start_time=start_time)
    if top_vod is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    top_series = _rank_matches(query, series_index, limit=5, start_time=start_time)
    if top_series is None:
        _notify_timeout()
        _safe_end_of_directory()
        return

    if not top_live and not top_vod and not top_series:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No matches",
            icon="INFO",
        )
        _safe_end_of_directory()
        return

    add_category_items(top_live, "live", max_items=2)
    add_category_items(top_vod, "vod", max_items=2)

    for entry, _ in top_series[:2]:
        series_id = entry.get("id")
        title = entry.get("title") or "Unknown Series"
        thumb = entry.get("thumb") or ""
        tmdb_id = entry.get("tmdb")

        url = _build_plugin_url(
            mode="list_series_seasons",
            series_id=series_id,
            series_name=title,
        )

        art = {"thumb": thumb, "poster": thumb} if thumb else None
        info = {"title": title, "mediatype": "tvshow"}
        props = {}
        if tmdb_id:
            props["tmdbnumber"] = str(tmdb_id)
            props["imdbnumber"] = str(tmdb_id)

        _add_directory_item(
            url,
            title,
            is_folder=True,
            art=art,
            info=info,
            properties=props,
        )

    _safe_end_of_directory()


def dynamic_filter_search(items, search_query=None):
    if not ensure_api_ready():
        return

    if not items:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No items to search",
            icon="INFO",
        )
        return

    search_query = _get_query(search_query, "Filter")
    if not search_query:
        return

    start_time = time.time()

    if navigator.PLUGIN_HANDLE >= 0:
        xbmcplugin.setPluginCategory(
            navigator.PLUGIN_HANDLE, "Filter: {}".format(search_query)
        )
        xbmcplugin.setContent(navigator.PLUGIN_HANDLE, "videos")

    matches = []

    for entry in items:
        if _timed_out(start_time):
            _notify_timeout()
            _safe_end_of_directory(navigator.PLUGIN_HANDLE)
            return

        raw_text = (
            entry.get("search_text")
            or entry.get("lower")
            or entry.get("title")
            or entry.get("name")
            or entry.get("category_name")
            or ""
        )
        text = _normalize_query(raw_text)

        raw_tokens = entry.get("search_tokens") or []
        tokens = [_normalize_query(t) for t in raw_tokens if t]

        score = _fast_score(search_query, text, tokens)

        if score <= 0.0:
            score = difflib.SequenceMatcher(
                None,
                _normalize_query(search_query),
                text,
            ).ratio()

        if score >= FUZZY_THRESHOLD:
            matches.append((entry, score))

    if not matches:
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "No matching items found",
            icon="INFO",
        )
        _safe_end_of_directory(navigator.PLUGIN_HANDLE)
        return

    matches.sort(key=lambda x: x[1], reverse=True)

    for entry, _ in matches:
        label = (
            entry.get("title")
            or entry.get("name")
            or entry.get("category_name")
            or "Unknown"
        )

        if entry.get("id") or entry.get("type") == "series":
            thumb = entry.get("thumb") or ""
            fanart = entry.get("fanart") or ""
            url = _build_plugin_url(
                mode="list_series_seasons",
                series_id=entry.get("id"),
                series_name=label,
            )
            _add_directory_item(
                url,
                label,
                is_folder=True,
                art={"thumb": thumb, "poster": thumb, "fanart": fanart},
                info={"title": label, "mediatype": "tvshow"},
            )
        else:
            url = _build_plugin_url(
                mode="play_stream" if entry.get("url") else "list_streams",
                stream_type=entry.get("stream_type", ""),
                category_id=entry.get("category_id", ""),
                category_name=label,
                url=entry.get("url", ""),
            )
            _add_directory_item(url, label, is_folder=True)

    _safe_end_of_directory(navigator.PLUGIN_HANDLE)
