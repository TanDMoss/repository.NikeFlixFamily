# resources/lib/cache/picon_cache.py
# -*- coding: utf-8 -*-

import os
import threading
import time
from urllib.parse import urlparse
from collections import OrderedDict

import requests
import xbmc
import xbmcvfs
import xbmcaddon

from resources.utils import giptv

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")

BASE_PROFILE = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")
CACHE_DIR = os.path.join(BASE_PROFILE, "picons")
PLACEHOLDER = os.path.join(
    xbmcvfs.translatePath("special://home"), "media", "DefaultVideo.png"
)
CACHE_EXPIRY_DAYS = 30

# Cap concurrent picon downloads so opening a directory doesn't explode thread count.
MAX_CONCURRENT_DOWNLOADS = 4

# Small bounded cache for server speed checks.
FAST_SERVER_CACHE_MAX = 200

# In-memory server speed cache and download tracking.
_fast_servers = OrderedDict()
_fast_servers_lock = threading.Lock()

_inflight_downloads = set()
_inflight_lock = threading.Lock()

_download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)


def _sanitize_filename(name):
    if isinstance(name, int):
        name = str(name)
    return "".join(c if c.isalnum() else "_" for c in name)


def _get_local_path(stream_id, category_id, url):
    cat_part = _sanitize_filename(category_id or "")
    filename = f"{_sanitize_filename(stream_id)}_{cat_part}.png"
    return os.path.join(CACHE_DIR, filename)


def _get_fast_server(host):
    with _fast_servers_lock:
        if host not in _fast_servers:
            return None
        _fast_servers.move_to_end(host)
        return _fast_servers[host]


def _set_fast_server(host, is_fast):
    with _fast_servers_lock:
        _fast_servers[host] = is_fast
        _fast_servers.move_to_end(host)
        while len(_fast_servers) > FAST_SERVER_CACHE_MAX:
            _fast_servers.popitem(last=False)


def _is_downloading(local_path):
    with _inflight_lock:
        return local_path in _inflight_downloads


def _mark_downloading(local_path):
    with _inflight_lock:
        if local_path in _inflight_downloads:
            return False
        _inflight_downloads.add(local_path)
        return True


def _unmark_downloading(local_path):
    with _inflight_lock:
        _inflight_downloads.discard(local_path)


def _download_async(url, local_path):
    if not _mark_downloading(local_path):
        return

    def _worker():
        try:
            with _download_semaphore:
                if os.path.exists(local_path):
                    return

                giptv.log(f"Downloading picon {url}", xbmc.LOGDEBUG)

                # Avoid half-written files being mistaken as complete.
                temp_path = local_path + ".part"

                r = requests.get(url, timeout=8, stream=True)
                r.raise_for_status()

                with open(temp_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)

                try:
                    os.replace(temp_path, local_path)
                except Exception:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                    raise

                giptv.log(f"Saved picon to {local_path}", xbmc.LOGDEBUG)

        except Exception as e:
            giptv.log(
                f"Exception while downloading picon {url}: {e}",
                xbmc.LOGDEBUG,
            )
            try:
                temp_path = local_path + ".part"
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
        finally:
            _unmark_downloading(local_path)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def get_picon(stream_id, url, category_id=None):
    """
    Return a picon path or remote URL.

    Behaviour:
    - cached local file -> return local path
    - fast server -> return remote URL directly
    - unknown/slow server -> return placeholder and schedule limited async download
    """
    if not url:
        return PLACEHOLDER

    local_path = _get_local_path(stream_id, category_id, url)

    if os.path.exists(local_path):
        return local_path

    host = urlparse(url).netloc
    is_fast = _get_fast_server(host)

    if is_fast is True:
        return url

    if is_fast is None:
        try:
            giptv.log(f"Probing picon server {host}", xbmc.LOGDEBUG)
            r = requests.head(url, timeout=0.5, allow_redirects=True)
            if r.status_code == 200:
                _set_fast_server(host, True)
                return url
            _set_fast_server(host, False)
        except Exception as e:
            giptv.log(f"Probe failed for {host}: {e}", xbmc.LOGDEBUG)
            _set_fast_server(host, False)

    # Slow or unknown server: return placeholder and download in background,
    # but only once per file and with capped concurrency.
    if not _is_downloading(local_path):
        _download_async(url, local_path)

    return PLACEHOLDER


def cleanup(expiry_days=CACHE_EXPIRY_DAYS):
    """
    Remove cached picons older than `expiry_days`.
    """
    now = time.time()
    removed_count = 0

    for fname in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, fname)
        if os.path.isfile(path):
            age_days = (now - os.path.getmtime(path)) / 86400
            if age_days > expiry_days:
                try:
                    os.remove(path)
                    removed_count += 1
                    giptv.log(f"Removed old picon {path}", xbmc.LOGINFO)
                except Exception as e:
                    giptv.log(f"Failed to remove picon {path}: {e}", xbmc.LOGWARNING)

    giptv.log(
        f"Cleanup complete, removed {removed_count} files",
        xbmc.LOGINFO,
    )
