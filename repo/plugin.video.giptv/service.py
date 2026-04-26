# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon
import xbmcvfs

from resources.utils import giptv
from resources.utils.config import ensure_api_ready
from resources.lib.cache.history_cache import shutdown_writer
from resources.lib.player.trakt_scrobbler import TraktPlayer
from resources.lib.player.proxy import ProxyPlayer
from resources.lib.pvr_bridge import ensure_pvr_playlist_ready
from resources.lib.proxy.proxy_instance import stop_proxy

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
STARTUP_DELAY_SECONDS = 8


def get_profile_path(subpath=""):
    base = "special://profile/addon_data/{}/".format(ADDON_ID)
    if subpath:
        base = base + subpath.lstrip("/")
    return xbmcvfs.translatePath(base)


def ensure_profile_dir():
    path = get_profile_path()
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)
    return path


def get_service_lock_path():
    ensure_profile_dir()
    return get_profile_path(".serviceRan")


def read_service_lock():
    path = get_service_lock_path()
    if not xbmcvfs.exists(path):
        return ""

    try:
        f = xbmcvfs.File(path, "r")
        try:
            return f.read().strip()
        finally:
            f.close()
    except Exception as e:
        giptv.log(f"Failed to read service lock: {e}", xbmc.LOGWARNING)
        return ""


def write_service_lock(version):
    ensure_profile_dir()
    path = get_service_lock_path()

    try:
        f = xbmcvfs.File(path, "w")
        try:
            f.write(str(version))
        finally:
            f.close()
    except Exception as e:
        giptv.log(f"Failed to write service lock: {e}", xbmc.LOGERROR)


def _version_tuple(version):
    try:
        return tuple(int(part) for part in str(version).split("."))
    except Exception:
        return (0, 0, 0)


def run_update_tasks_once():
    current_version = ADDON.getAddonInfo("version")
    last_ran_version = read_service_lock()

    if last_ran_version == current_version:
        giptv.log(f"Update tasks already ran for {current_version}", xbmc.LOGINFO)
        return

    giptv.log(
        f"Running one-time update tasks for {current_version} (previous: {last_ran_version or 'none'})",
        xbmc.LOGINFO,
    )

    if _version_tuple(current_version) <= _version_tuple("2.6.1"):
        giptv.log("Applying legacy cache reset", xbmc.LOGINFO)
        giptv.wipe_all_thumbnails()
        giptv.clear_cache()

    write_service_lock(current_version)
    giptv.log("One-time update tasks complete; startup changelog suppressed", xbmc.LOGINFO)


# ============================================================
#  SETTINGS MONITOR
# ============================================================
class SettingsMonitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()

    def onSettingsChanged(self):
        """
        Triggered when addon settings change.
        We:
          - refresh containers
          - request index rebuild
        """
        giptv.log("Settings Changed", xbmc.LOGINFO)

        giptv.container_refresh()


# ============================================================
#  MAIN SERVICE LOOP
# ============================================================
if __name__ == "__main__":
    monitor = SettingsMonitor()

    giptv.log(
        f"Deferring GIPTV background startup work for {STARTUP_DELAY_SECONDS} seconds",
        xbmc.LOGINFO,
    )
    try:
        if monitor.waitForAbort(STARTUP_DELAY_SECONDS):
            giptv.log("Service aborted before deferred startup work", xbmc.LOGINFO)
        else:
            player = TraktPlayer()
            proxy_player = ProxyPlayer()

            giptv.log("Trakt player monitor initialized", xbmc.LOGINFO)
            giptv.log("Proxy player monitor initialized", xbmc.LOGINFO)

            run_update_tasks_once()

            if ensure_api_ready():
                ensure_pvr_playlist_ready()
                giptv.log("Service initialized with deferred minimal work", xbmc.LOGINFO)
                # Do not preload EPG here.
                # Do not ensure/build search index here.
                # Do not force-release locks here.

        giptv.log("Entering main monitor loop", xbmc.LOGINFO)
        while not monitor.abortRequested():
            if monitor.waitForAbort(1):
                break
    finally:
        try:
            stop_proxy()
        except Exception:
            pass
        shutdown_writer()
        giptv.log("Service shutting down", xbmc.LOGINFO)
