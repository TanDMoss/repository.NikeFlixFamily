# -*- coding: utf-8 -*-
try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

import sys
import json
import time
import base64
import datetime

import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs

from resources.utils import settings
from resources.utils import giptv
from resources.lib.manager.epg_manager import get_xmltv_index, get_now_next

ADDON = xbmcaddon.Addon()

if len(sys.argv) > 1 and sys.argv[1].isdigit():
    PLUGIN_HANDLE = int(sys.argv[1])
else:
    PLUGIN_HANDLE = -1

ADDON_ID = ADDON.getAddonInfo("id")

FAVOURITES_PATH = xbmcvfs.translatePath(
    f"special://profile/addon_data/{ADDON_ID}/favourites.json"
)


def _encode_meta(meta_dict):
    try:
        raw = json.dumps(meta_dict, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


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


def _normalize_title(value):
    return (value or "").strip().lower()


def _sort_favourites(items, mode):
    if not mode:
        return items

    if mode == "recent":
        return sorted(
            items,
            key=lambda x: x.get("added_at", x.get("timestamp", 0)),
            reverse=True,
        )

    if mode == "oldest":
        return sorted(
            items,
            key=lambda x: x.get("added_at", x.get("timestamp", 0)),
        )

    if mode == "za":
        return sorted(
            items,
            key=lambda x: _normalize_title(x.get("title", "")),
            reverse=True,
        )

    return sorted(
        items,
        key=lambda x: _normalize_title(x.get("title", "")),
    )


def _build_live_epg(channel_id):
    if not channel_id:
        return None

    try:
        epg_offset_minutes = settings.get_epg_offset(ADDON)
        xmltv_index = get_xmltv_index()
        data = get_now_next(xmltv_index, channel_id, epg_offset_minutes)

        if not data or not data.get("now"):
            return None

        title, desc, start_ts, end_ts = data["now"]
        duration = max(0, end_ts - start_ts)

        display_start_ts = start_ts - (epg_offset_minutes * 60)
        display_end_ts = end_ts - (epg_offset_minutes * 60)

        pct = _epg_progress(display_start_ts, display_end_ts)
        bar = _progress_bar(pct)

        plot_lines = [
            f"[COLOR yellow][B]Now: {title}[/B][/COLOR] "
            f"[COLOR grey][I]from {_fmt_time(display_start_ts)} – {_fmt_time(display_end_ts)}[/I][/COLOR]",
            f"[COLOR green]{bar}  {pct}%[/COLOR]",
            f"[COLOR white]{desc}[/COLOR]",
        ]

        if data.get("next"):
            next_title, next_desc, next_start, next_end = data["next"]
            display_next_start = next_start - (epg_offset_minutes * 60)
            display_next_end = next_end - (epg_offset_minutes * 60)

            plot_lines += [
                f"[COLOR yellow][B]Next: {next_title}[/B][/COLOR] "
                f"[COLOR grey][I]from {_fmt_time(display_next_start)} – {_fmt_time(display_next_end)}[/I][/COLOR]",
                f"[COLOR white]{next_desc}[/COLOR]",
            ]

        return {
            "title": title,
            "plot": "\n".join(plot_lines),
            "duration": duration,
        }
    except Exception:
        return None


def _read():
    if not xbmcvfs.exists(FAVOURITES_PATH):
        return []

    try:
        f = xbmcvfs.File(FAVOURITES_PATH, "r")
        data = json.loads(f.read())
        f.close()
    except Exception:
        return []

    cleaned = _autoclean(data)

    if cleaned != data:
        _write(cleaned)

    return cleaned


def _write(data):
    try:
        f = xbmcvfs.File(FAVOURITES_PATH, "w")
        f.write(json.dumps(data))
        f.close()
    except Exception:
        pass


def _autoclean(data):
    cleaned = []

    for item in data or []:
        item_id = item.get("id")
        favourite_kind = item.get("favourite_kind", "playable")
        play_url = item.get("play_url")

        if not item_id:
            continue

        if favourite_kind == "playable":
            if not play_url or "." not in play_url:
                continue
            if "None" in play_url or play_url.endswith("/") or play_url.endswith(".."):
                continue

        if "added_at" not in item:
            item["added_at"] = item.get("timestamp", int(time.time()))

        cleaned.append(item)

    return cleaned


def add_favourite(
    item_id,
    title,
    stream_type,
    play_url="",
    thumb="",
    poster="",
    fanart="",
    icon="",
    plot="",
    rating=0,
    year=0,
    tmdb_id="",
    channel_id="",
    stream_id="",
    favourite_kind="playable",
    target_mode="",
    series_id="",
    series_name="",
    season_num="",
):
    data = _read()
    data = [i for i in data if str(i.get("id")) != str(item_id)]

    now_ts = int(time.time())

    payload = {
        "id": item_id,
        "title": title,
        "type": stream_type,
        "thumb": thumb or "",
        "poster": poster or "",
        "fanart": fanart or "",
        "icon": icon or "",
        "plot": plot or "",
        "rating": rating or 0,
        "year": year or 0,
        "tmdb_id": tmdb_id or "",
        "play_url": play_url or "",
        "channel_id": channel_id or "",
        "stream_id": str(stream_id or ""),
        "is_live_epg": (stream_type == "live"),
        "timestamp": now_ts,
        "added_at": now_ts,
        "favourite_kind": favourite_kind or "playable",
        "target_mode": target_mode or "",
        "series_id": str(series_id or ""),
        "series_name": series_name or "",
        "season_num": str(season_num or ""),
    }

    data.insert(0, payload)
    _write(data)


def remove_favourite(item_id):
    data = _read()
    data = [i for i in data if str(i.get("id")) != str(item_id)]
    _write(data)


def is_favourite(item_id):
    return any(str(i.get("id")) == str(item_id) for i in _read())


def toggle_favourite(
    item_id,
    title,
    stream_type,
    play_url="",
    thumb="",
    poster="",
    fanart="",
    icon="",
    plot="",
    rating=0,
    year=0,
    tmdb_id="",
    channel_id="",
    stream_id="",
    favourite_kind="playable",
    target_mode="",
    series_id="",
    series_name="",
    season_num="",
):
    if is_favourite(item_id):
        remove_favourite(item_id)
        return False

    add_favourite(
        item_id=item_id,
        title=title,
        stream_type=stream_type,
        play_url=play_url,
        thumb=thumb,
        poster=poster,
        fanart=fanart,
        icon=icon,
        plot=plot,
        rating=rating,
        year=year,
        tmdb_id=tmdb_id,
        channel_id=channel_id,
        stream_id=stream_id,
        favourite_kind=favourite_kind,
        target_mode=target_mode,
        series_id=series_id,
        series_name=series_name,
        season_num=season_num,
    )
    return True


def add_favourite_from_params(
    item_id,
    title,
    stream_type,
    play_url="",
    thumb="",
    poster="",
    fanart="",
    icon="",
    plot="",
    rating=0,
    year=0,
    tmdb_id="",
    channel_id="",
    stream_id="",
    favourite_kind="playable",
    target_mode="",
    series_id="",
    series_name="",
    season_num="",
):
    add_favourite(
        item_id=item_id,
        title=title,
        stream_type=stream_type,
        play_url=play_url,
        thumb=thumb,
        poster=poster,
        fanart=fanart,
        icon=icon,
        plot=plot,
        rating=rating,
        year=year,
        tmdb_id=tmdb_id,
        channel_id=channel_id,
        stream_id=stream_id,
        favourite_kind=favourite_kind,
        target_mode=target_mode,
        series_id=series_id,
        series_name=series_name,
        season_num=season_num,
    )


def remove_favourite_from_params(item_id):
    remove_favourite(item_id)


def _build_folder_url(entry):
    target_mode = entry.get("target_mode", "")
    series_id = entry.get("series_id", "")
    series_name = entry.get("series_name", "") or entry.get("title", "")
    season_num = entry.get("season_num", "")
    poster = entry.get("poster", "")
    fanart = entry.get("fanart", "")
    tmdb_id = entry.get("tmdb_id", "")

    if target_mode == "list_series_seasons" and series_id:
        return (
            sys.argv[0]
            + "?"
            + urlparse.urlencode(
                {
                    "mode": "list_series_seasons",
                    "series_id": series_id,
                    "series_name": series_name,
                }
            )
        )

    if target_mode == "list_series_episodes" and series_id and season_num:
        return (
            sys.argv[0]
            + "?"
            + urlparse.urlencode(
                {
                    "mode": "list_series_episodes",
                    "series_id": series_id,
                    "season_num": season_num,
                    "series_name": series_name,
                    "series_poster": poster,
                    "series_fanart": fanart,
                    "tmdb_id": tmdb_id,
                }
            )
        )

    return ""


def list_favourites():
    from resources.lib.manager import sort_manager

    favourites = _read()
    sort_mode = sort_manager.get_current_sort("favourites", "main")
    sort_label = sort_manager.get_sort_label("favourites", "main")
    favourites = _sort_favourites(favourites, sort_mode)

    xbmcplugin.setPluginCategory(PLUGIN_HANDLE, "Favourites")
    xbmcplugin.setContent(PLUGIN_HANDLE, "videos")

    if not favourites:
        item = xbmcgui.ListItem("No favourites yet.")
        xbmcplugin.addDirectoryItem(PLUGIN_HANDLE, "", item, isFolder=False)
        xbmcplugin.endOfDirectory(PLUGIN_HANDLE)
        return

    sort_item = xbmcgui.ListItem(label=f"[COLOR cyan]{sort_label}[/COLOR]")
    sort_item.setArt({"icon": "DefaultAddonProgram.png"})
    xbmcplugin.addDirectoryItem(
        PLUGIN_HANDLE,
        giptv.build_url(
            action="cycle_sort",
            directory_type="favourites",
            directory_id="main",
            refresh_mode="favourites",
        ),
        sort_item,
        isFolder=False,
    )

    for entry in favourites:
        title = entry.get("title", "Unknown")
        thumb = entry.get("thumb", "")
        poster = entry.get("poster", "")
        fanart = entry.get("fanart", "")
        icon = entry.get("icon", "")
        plot = entry.get("plot", "")
        rating = entry.get("rating", 0)
        year = entry.get("year", 0)
        tmdb_id = entry.get("tmdb_id", "")
        play_url = entry.get("play_url", "")
        stream_type = entry.get("type", "vod")
        stream_id = entry.get("stream_id") or entry.get("id", "")
        channel_id = entry.get("channel_id", "")
        is_live_epg = entry.get("is_live_epg", False)
        favourite_kind = entry.get("favourite_kind", "playable")

        display_title = title
        display_plot = plot

        if stream_type == "live" and is_live_epg and channel_id:
            live_epg = _build_live_epg(channel_id)
            if live_epg:
                display_plot = live_epg.get("plot", plot)

        li = xbmcgui.ListItem(label=display_title)
        li.setArt(
            {
                "thumb": thumb or poster or fanart or icon or "DefaultVideo.png",
                "icon": icon or thumb or poster or fanart or "DefaultVideo.png",
                "poster": poster or thumb or fanart or icon or "DefaultVideo.png",
                "fanart": fanart or poster or thumb or icon or "DefaultVideo.png",
            }
        )

        tag = li.getVideoInfoTag()
        tag.setTitle(display_title)
        tag.setPlot(display_plot)

        if stream_type == "series":
            if favourite_kind == "series_folder":
                tag.setMediaType("tvshow")
            elif favourite_kind == "season_folder":
                tag.setMediaType("season")
            else:
                tag.setMediaType("episode")
        elif stream_type == "vod":
            tag.setMediaType("movie")
        else:
            tag.setMediaType("video")

        if year:
            try:
                tag.setYear(int(year))
            except Exception:
                pass

        if rating:
            try:
                tag.setRating(float(rating), 10)
            except Exception:
                pass

        if tmdb_id:
            li.setProperty("tmdbnumber", str(tmdb_id))
            li.setProperty("imdbnumber", str(tmdb_id))

        custom_menu_url = giptv.build_url(
            action="open_context_window",
            title=display_title,
            item_id=entry.get("id", ""),
            name=title,
            play_url=play_url,
            stream_type=stream_type,
            thumb=thumb,
            poster=poster,
            fanart=fanart,
            icon=icon,
            plot=display_plot,
            rating=str(rating),
            year=str(year),
            tmdb_id=tmdb_id,
            channel_id=channel_id,
            epg_channel_id=channel_id,
            has_archive="0",
            directory_type="favourites",
            directory_id="main",
            refresh_mode="favourites",
            sort_label=sort_label,
            category_id="",
            category_name="Favourites",
            search_query="",
            favourite_kind=favourite_kind,
            target_mode=entry.get("target_mode", ""),
            series_id=entry.get("series_id", ""),
            series_name=entry.get("series_name", ""),
            season_num=entry.get("season_num", ""),
        )
        li.addContextMenuItems(
            [("GIPTV Menu", f"RunPlugin({custom_menu_url})")],
            replaceItems=False,
        )

        if favourite_kind in ("series_folder", "season_folder"):
            folder_url = _build_folder_url(entry)
            xbmcplugin.addDirectoryItem(
                PLUGIN_HANDLE,
                folder_url,
                li,
                isFolder=True,
            )
        else:
            meta = {
                "thumb": thumb,
                "poster": poster,
                "fanart": fanart,
                "icon": icon,
                "plot": display_plot,
                "rating": rating,
                "year": year,
                "tmdb_id": tmdb_id,
                "stream_type": stream_type,
                "channel_id": channel_id,
                "stream_id": stream_id,
                "season": entry.get("season_num", ""),
            }

            plugin_url = (
                sys.argv[0]
                + "?"
                + urlparse.urlencode(
                    {
                        "mode": "play_stream",
                        "url": play_url,
                        "id": stream_id,
                        "type": stream_type,
                        "name": title,
                        "meta": _encode_meta(meta),
                    }
                )
            )

            li.setProperty("IsPlayable", "true")

            if stream_type == "live":
                li.setProperty("IsLive", "true")

            xbmcplugin.addDirectoryItem(
                PLUGIN_HANDLE,
                plugin_url,
                li,
                isFolder=False,
            )

    xbmcplugin.endOfDirectory(PLUGIN_HANDLE)
