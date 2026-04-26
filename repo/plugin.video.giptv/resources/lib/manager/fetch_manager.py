# -*- coding: utf-8 -*-
import time
import json

import xbmc
import xbmcaddon

from resources.lib.cache.cachedb import CacheDB

# --- CACHE TIME CONSTANTS (in seconds) ---
NEVER_EXPIRE = 999999999  # approx 31 years

CACHE_DURATION = {
    "CATEGORIES": 86400 * 30,  # 30 days
    "LIVE_STREAMS": 86400 * 30,  # 30 days
    "VOD_STREAMS": 86400 * 7,  # 7 days
    "SERIES_STREAMS": 86400 * 14,  # 14 days
    "SERIES_INFO": 86400 * 14,  # 14 days
    "TMDB_DATA": NEVER_EXPIRE,
}

ADDON = xbmcaddon.Addon()


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[GIPTV] [FETCH_MANAGER] {msg}", level)


class FetchCache:
    """
    Middleman for cached reads/writes.
    Determines expiration and delegates storage to CacheDB instances.
    """

    def __init__(self):
        self.db_map = {
            "categories": ("categories.db", "CATEGORIES"),
            "live": ("live_streams.db", "LIVE_STREAMS"),
            "vod": ("vod_streams.db", "VOD_STREAMS"),
            "series": ("series_streams.db", "SERIES_STREAMS"),
            "series_info": ("series_info.db", "SERIES_INFO"),
            "tmdb_data": ("tmdb_data.db", "TMDB_DATA"),
        }
        self.db_instances = {}
        self._initialize_instances()

    def _initialize_instances(self):
        for content_type, (filename, _) in self.db_map.items():
            try:
                self.db_instances[content_type] = CacheDB(filename)
            except Exception as e:
                _log(f"Failed to initialize DB for {content_type}: {e}", xbmc.LOGERROR)

    def has_type(self, content_type):
        return content_type in self.db_map and content_type in self.db_instances

    def get_duration(self, content_type):
        if content_type not in self.db_map:
            return 0
        duration_key = self.db_map[content_type][1]
        return CACHE_DURATION.get(duration_key, 0)

    def get(self, content_type, key):
        """
        Retrieve cached JSON payload and return deserialized data,
        or None if missing/expired/invalid.
        """
        if not self.has_type(content_type):
            return None

        db_instance = self.db_instances[content_type]
        duration = self.get_duration(content_type)

        try:
            raw_data = db_instance.get_raw(key)
        except Exception as e:
            _log(f"get_raw failed for {content_type}:{key}: {e}", xbmc.LOGWARNING)
            return None

        if raw_data is None:
            return None

        try:
            data_json, timestamp = raw_data
        except Exception:
            _log(f"Malformed raw cache entry for {content_type}:{key}", xbmc.LOGWARNING)
            return None

        try:
            timestamp = float(timestamp or 0)
        except Exception:
            timestamp = 0

        if timestamp and (time.time() - timestamp >= duration):
            try:
                db_instance.delete(key)
            except Exception as e:
                _log(
                    f"Failed deleting expired key {content_type}:{key}: {e}",
                    xbmc.LOGWARNING,
                )
            return None

        try:
            return json.loads(data_json)
        except Exception as e:
            _log(f"JSON decode failed for {content_type}:{key}: {e}", xbmc.LOGWARNING)
            try:
                db_instance.delete(key)
            except Exception:
                pass
            return None

    def set(self, content_type, key, data):
        """
        Store JSON-serializable data using the underlying CacheDB instance.
        """
        if not self.has_type(content_type):
            return

        try:
            self.db_instances[content_type].set_raw(key, data)
        except Exception as e:
            _log(f"set_raw failed for {content_type}:{key}: {e}", xbmc.LOGWARNING)

    def delete(self, content_type, key):
        if not self.has_type(content_type):
            return
        try:
            self.db_instances[content_type].delete(key)
        except Exception as e:
            _log(f"delete failed for {content_type}:{key}: {e}", xbmc.LOGWARNING)

    def close(self):
        for content_type, db in self.db_instances.items():
            try:
                db.close()
            except Exception as e:
                _log(f"Failed closing DB {content_type}: {e}", xbmc.LOGWARNING)

    def cleanup_expired_known_keys(self, content_type, keys):
        """
        Lightweight helper when caller already knows a small set of keys.
        Avoids full-table scans but can prune obvious expired entries.
        """
        if not self.has_type(content_type):
            return

        db_instance = self.db_instances[content_type]
        duration = self.get_duration(content_type)
        now = time.time()

        for key in keys or []:
            try:
                raw_data = db_instance.get_raw(key)
                if not raw_data:
                    continue

                _, timestamp = raw_data
                timestamp = float(timestamp or 0)

                if timestamp and (now - timestamp >= duration):
                    db_instance.delete(key)
            except Exception:
                continue


cache_handler = FetchCache()
