# -*- coding: utf-8 -*-
import os
import time

import xbmc
import xbmcvfs

import resources.apis.xtream_api as xtream_api
import resources.lib.live_guide as live_guide
import resources.utils.giptv as giptv
from resources.utils.config import ensure_api_ready


PVR_PLAYLIST_SPECIAL = "special://profile/addon_data/pvr.iptvsimple/giptv-live.m3u"
PVR_PLAYLIST_MAX_AGE_SECONDS = 12 * 60 * 60


def _playlist_path():
    return xbmcvfs.translatePath(PVR_PLAYLIST_SPECIAL)


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _needs_refresh(path, max_age_seconds):
    if not os.path.exists(path):
        return True

    try:
        return (time.time() - os.path.getmtime(path)) > max_age_seconds
    except Exception:
        return True


def _m3u_attr(value):
    value = str(value or "")
    value = value.replace("&", "&amp;")
    value = value.replace('"', "'")
    value = value.replace("\r", " ").replace("\n", " ")
    return value.strip()


def _stream_url(stream):
    stream_id = stream.get("stream_id")
    if not stream_id:
        return ""

    extension = stream.get("container_extension") or "ts"
    return xtream_api.build_stream_url(stream_id, xtream_api.LIVE_TYPE, extension) or ""


def _live_category_names():
    categories = xtream_api.categories(xtream_api.LIVE_TYPE) or []
    names = {}
    for category in categories:
        category_id = category.get("category_id")
        category_name = category.get("category_name")
        if category_id not in (None, "") and category_name:
            names[str(category_id)] = category_name
    return names


def _stream_group(stream, category_names):
    category_id = stream.get("category_id")
    if category_id not in (None, ""):
        category_name = category_names.get(str(category_id))
        if category_name:
            return category_name
    return stream.get("category_name") or "Live TV"


def _stream_lines(stream, category_names):
    name = _m3u_attr(stream.get("name") or "Live Channel")
    stream_url = _stream_url(stream)
    if not stream_url:
        return []

    tvg_id = _m3u_attr(stream.get("epg_channel_id") or stream.get("stream_id") or name)
    logo = _m3u_attr(stream.get("stream_icon") or "")
    group = _m3u_attr(_stream_group(stream, category_names))

    return [
        '#EXTINF:-1 tvg-id="{}" tvg-name="{}" tvg-logo="{}" group-title="{}",{}'.format(
            tvg_id,
            name,
            logo,
            group,
            name,
        ),
        stream_url,
    ]


def _write_playlist(path, streams, category_names):
    _ensure_parent_dir(path)

    lines = ["#EXTM3U"]
    for stream in streams:
        lines.extend(_stream_lines(stream, category_names))

    with open(path, "w", encoding="utf-8", newline="\n") as playlist:
        playlist.write("\n".join(lines))
        playlist.write("\n")

    return max(0, len(lines) - 1) // 2


def ensure_pvr_playlist_ready(force=False, max_age_seconds=PVR_PLAYLIST_MAX_AGE_SECONDS):
    path = _playlist_path()

    if not force and not _needs_refresh(path, max_age_seconds):
        giptv.log("PVR bridge playlist is fresh", xbmc.LOGINFO)
        return True

    if not ensure_api_ready():
        giptv.log("PVR bridge skipped because Xtream API is not configured", xbmc.LOGWARNING)
        return False

    streams = [
        stream
        for stream in xtream_api.get_live_streams() or []
        if live_guide.is_supported_region_stream(stream)
    ]
    if not streams:
        giptv.log("PVR bridge skipped because no live streams were returned", xbmc.LOGWARNING)
        return False

    category_names = _live_category_names()
    count = _write_playlist(path, streams, category_names)
    giptv.log(
        "PVR bridge playlist refreshed with {} channels at {}".format(
            count,
            PVR_PLAYLIST_SPECIAL,
        ),
        xbmc.LOGINFO,
    )
    return count > 0
