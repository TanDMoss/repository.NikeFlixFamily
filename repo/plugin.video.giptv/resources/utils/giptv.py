# -*- coding: utf-8 -*-
"""
giptv.py
Includes functions for:
- Addon info & versioning
- GUI / dialogs
- File & path management
- Playback & playlists
- Plugin routing
- JSON-RPC / system settings
- Settings XML parsing
- General utilities
"""

import os
import shutil
import json
import time
import sys
import urllib.parse as urlparse
import requests
import xml.etree.ElementTree as ET
import inspect
from json import dumps as jsdumps, loads as jsloads
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import webbrowser

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs
import xbmcaddon

###################################################
# Addon & Kodi Info Helpers
###################################################

AddonInstance = xbmcaddon.Addon()
AddonID = AddonInstance.getAddonInfo("id")
addonNameStr = AddonInstance.getAddonInfo("name")

PROFILE_PATH = AddonInstance.getAddonInfo("profile")
ADDON_PROFILE = xbmcvfs.translatePath(PROFILE_PATH)
CACHE_DIR = os.path.join(ADDON_PROFILE, "cache")
SETTINGS_FILE = os.path.join(ADDON_PROFILE, "settings.xml")
ADDON_PATH = xbmcvfs.translatePath(AddonInstance.getAddonInfo("path"))
joinPath = os.path.join


def addon(addon_id=AddonID):
    return xbmcaddon.Addon(addon_id)


def addon_installed(addon_id):
    return xbmc.getCondVisibility(f"System.HasAddon({addon_id})")


def addon_enabled(addon_id):
    return xbmc.getCondVisibility(f"System.AddonIsEnabled({addon_id})")


def addon_info(info):
    return AddonInstance.getAddonInfo(info)


def addon_version():
    return AddonInstance.getAddonInfo("version")


def addon_path():
    return ADDON_PATH


def addon_profile():
    return ADDON_PROFILE


def addon_icon():
    return xbmcvfs.translatePath(addon_info("icon"))


def addon_fanart():
    return xbmcvfs.translatePath(addon_info("fanart"))


def kodi_version():
    return int(xbmc.getInfoLabel("System.BuildVersion")[0:2])


def translate_path(path):
    return xbmcvfs.translatePath(path)


###################################################
# Settings Helpers (XML / Window Properties)
###################################################


def setting(id, fallback=None):
    try:
        settings_dict = json.loads(kodi_window().getProperty("giptv_settings"))
    except Exception:
        settings_dict = make_settings_dict() or {}

    value = settings_dict.get(id, "")
    if fallback is None:
        return value
    return value if value != "" else fallback


def lang(language_id):
    return str(AddonInstance.getLocalizedString(language_id))


def appearance():
    return setting("appearance.1", fallback="default").lower()


def art_path():
    theme = appearance()
    return os.path.join(addon_path(), "resources", "media", theme)


def addon_icon_path():
    theme_icon = os.path.join(art_path(), "icon.png")
    return theme_icon if os.path.exists(theme_icon) else addon_icon()


###################################################
# GUI / Dialog Helpers
###################################################

dialog = xbmcgui.Dialog()
homeWindow = xbmcgui.Window(10000)


def kodi_window():
    return homeWindow


def notification(title=None, message=None, icon=None, time_ms=3000, sound=True):
    if title in (None, "default"):
        title = addonNameStr
    if icon in (None, "default"):
        icon = addon_icon_path()
    return dialog.notification(str(title), str(message), icon, time_ms, sound)


def ok_dialog(title=None, message=None):
    if title in (None, "default"):
        title = addonNameStr
    return dialog.ok(str(title), str(message))


def yesno_dialog(
    line1, line2="", line3="", heading=addonNameStr, nolabel="", yeslabel=""
):
    message = f"{line1}[CR]{line2}[CR]{line3}"
    return dialog.yesno(heading, message, nolabel, yeslabel)


def select_dialog(options, heading=addonNameStr):
    return dialog.select(heading, options)


def context_menu(items=None, labels=None):
    if items:
        labels = [i[0] for i in items]
        choice = dialog.contextmenu(labels)
        if choice >= 0:
            return items[choice][1]()
        return False
    elif labels:
        return dialog.contextmenu(labels)


def hide_dialogs():
    xbmc.executebuiltin("Dialog.Close(busydialog)")
    xbmc.executebuiltin("Dialog.Close(busydialognocancel)")


def close_all_dialogs():
    xbmc.executebuiltin("Dialog.Close(all,true)")


def close_ok_dialog():
    xbmc.executebuiltin("Dialog.Close(okdialog,true)")


###################################################
# File & Path Helpers
###################################################


def path_exists(path):
    return xbmcvfs.exists(path)


def list_dirs(path):
    return xbmcvfs.listdir(path)


def make_directory(path):
    xbmcvfs.mkdir(path)


def delete_file(path):
    xbmcvfs.delete(path)


def delete_folder(path, force=False):
    xbmcvfs.rmdir(path, force)


def copy_file(src, dst):
    xbmcvfs.copy(src, dst)


def rename_file(old, new):
    xbmcvfs.rename(old, new)


def open_file(path, mode="r"):
    return xbmcvfs.File(path, mode)


def clear_cache():
    try:
        hide_dialogs()

        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR, exist_ok=True)

        notification("Cache Cleared")
        log("Cache cleared", xbmc.LOGINFO)
    except Exception as e:
        log(f"Failed to clear cache: {e}", xbmc.LOGERROR)


###################################################
# Media & Playback Helpers
###################################################


def build_url(**params):
    return sys.argv[0] + "?" + urlparse.urlencode(params)


def make_listitem(label="", icon=None, fanart=None, info=None):
    listitem = xbmcgui.ListItem(label)
    art = {"icon": icon or "", "thumb": icon or "", "fanart": fanart or ""}
    listitem.setArt(art)
    if info:
        listitem.setInfo("video", info)
    return listitem


def add_item(handle, url, listitem, is_folder=True):
    xbmcplugin.addDirectoryItem(handle, url, listitem, is_folder)


def end_directory(handle, succeeded=True, update_listing=False, cache_to_disc=False):
    xbmcplugin.endOfDirectory(
        handle,
        succeeded=succeeded,
        updateListing=update_listing,
        cacheToDisc=cache_to_disc,
    )


def play_media(url, listitem=None):
    xbmc.Player().play(url, listitem)


def make_playlist(playlist_type="video"):
    return xbmc.PlayList({"music": 0, "video": 1}[playlist_type])


###################################################
# Plugin / URL Routing Helpers
###################################################


def run_plugin(params=None, block=False):
    params = params or {}
    xbmc.executebuiltin(f"RunPlugin({build_url(**params)})", block)


def container_update(params=None, block=False):
    params = params or {}
    xbmc.executebuiltin(f"Container.Update({build_url(**params)})", block)


def safe_container_update(params=None, block=False):
    params = params or {}
    url = build_url(**params)
    log(f"Container.Update -> {url}", xbmc.LOGINFO)
    xbmc.executebuiltin(f"Container.Update({url})", block)


def container_refresh():
    xbmc.executebuiltin("Container.Refresh")
    log("Container refreshed", xbmc.LOGINFO)


def safe_refresh_container():
    log("Refreshing current container", xbmc.LOGINFO)
    xbmc.executebuiltin("Container.Refresh")


def return_action():
    # Keep for rare manual use, but avoid using this as a normal navigation tool.
    log("Action(Back) requested", xbmc.LOGWARNING)
    xbmc.executebuiltin("Action(Back)")


###################################################
# JSON-RPC Helpers
###################################################


def jsonrpc_call(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        payload["params"] = params
    response = xbmc.executeJSONRPC(json.dumps(payload))
    return json.loads(response).get("result", None)


def get_system_setting(setting_id, default=None):
    try:
        return jsonrpc_call("Settings.GetSettingValue", {"setting": setting_id})[
            "value"
        ]
    except Exception:
        return default


###################################################
# Utilities
###################################################


def sleep(ms):
    xbmc.sleep(ms)


def execute_builtin(command, block=False):
    xbmc.executebuiltin(command, block)


def log(msg, level=xbmc.LOGINFO, tag=None):
    if tag is None:
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        if module and module.__file__:
            tag = os.path.splitext(os.path.basename(module.__file__))[0]
        else:
            tag = "UNKNOWN"

    xbmc.log(f"[GIPTV] [{tag.upper()}] {msg}", level)


def time_it(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        log(f"{func.__name__} executed in {time.time() - start:.2f}s")
        return result

    return wrapper


def open_settings():
    try:
        xbmc.sleep(200)
        AddonInstance.openSettings()
    except Exception as e:
        log(f"Error opening settings: {e}", xbmc.LOGERROR)


def make_settings_dict():
    settings_path = joinPath(addon_profile(), "settings.xml")
    settings_dict = {}

    try:
        tree = ET.parse(settings_path)
        root = tree.getroot()
        for item in root.findall("setting"):
            sid = item.get("id")
            val = item.text or ""
            settings_dict[sid] = val

        kodi_window().setProperty("giptv_settings", jsdumps(settings_dict))
    except Exception:
        settings_dict = {}

    return settings_dict


def close_setting(save_to_file=True):
    """
    Close settings dialog and persist cached settings values.
    Avoid forcing root navigation + refresh here.
    """
    execute_builtin("Dialog.Close(addonsettings)")
    xbmc.sleep(200)

    if save_to_file:
        try:
            settings_path = os.path.join(addon_profile(), "settings.xml")
            tree = None
            root = None

            if xbmcvfs.exists(settings_path):
                tree = ET.parse(settings_path)
                root = tree.getroot()
            else:
                root = ET.Element("settings")
                tree = ET.ElementTree(root)

            settings_dict = jsloads(kodi_window().getProperty("giptv_settings") or "{}")
            kodi_window().setProperty("giptv_settings", jsdumps(settings_dict))

            for sid, val in settings_dict.items():
                elem = root.find(f".//setting[@id='{sid}']")
                if elem is None:
                    elem = ET.SubElement(root, "setting", {"id": sid})
                elem.text = str(val)

            tree.write(settings_path, encoding="utf-8", xml_declaration=True)

            make_settings_dict()
            log("Settings saved and updated", xbmc.LOGINFO)
        except Exception as e:
            log(f"Failed to save settings: {e}", xbmc.LOGERROR)


def make_session(url_prefix="https://"):
    session = requests.Session()

    retries = Retry(total=3, backoff_factor=0.3)
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount(url_prefix, adapter)

    return session


def donate():
    url = "https://revolut.me/enoch1urd"
    webbrowser.open(url)


def wipe_all_thumbnails():
    thumb_path = xbmcvfs.translatePath("special://profile/Thumbnails/")

    if not xbmcvfs.exists(thumb_path):
        log("Thumbnail folder does not exist", xbmc.LOGINFO)
        return

    removed = 0

    try:
        dirs, files = xbmcvfs.listdir(thumb_path)

        for file_name in files:
            full = os.path.join(thumb_path, file_name)
            try:
                if xbmcvfs.delete(full):
                    removed += 1
            except Exception:
                pass

        for folder in dirs:
            folder_path = os.path.join(thumb_path, folder)
            try:
                subdirs, subfiles = xbmcvfs.listdir(folder_path)

                for subfile in subfiles:
                    full = os.path.join(folder_path, subfile)
                    try:
                        if xbmcvfs.delete(full):
                            removed += 1
                    except Exception:
                        pass

                try:
                    xbmcvfs.rmdir(folder_path)
                except Exception:
                    pass
            except Exception:
                pass

        log(f"Thumbnail cache wiped ({removed} files removed)", xbmc.LOGINFO)

    except Exception as e:
        log(f"Failed to wipe thumbnails: {e}", xbmc.LOGERROR)


def open_tools_window():
    from resources.lib.windows.tools_menu import GIPTVToolsMenu
    from resources.apis import trakt_api

    is_authed = trakt_api.trakt_is_authenticated()
    trakt_username = trakt_api.trakt_get_username() or "Connected"

    items = [
        {"key": "open_settings", "label": "Open Addon Settings"},
        {"key": "build_search_index", "label": "Build Search Index"},
        {"key": "clear_cache", "label": "Clear Cache"},
        {"key": "clear_history", "label": "Clear Recently Watched"},
    ]

    if is_authed:
        items.append({"key": "trakt_status", "label": f"Trakt: {trakt_username}"})
        items.append({"key": "trakt_auth_test", "label": "Test Trakt Connection"})
        items.append({"key": "trakt_revoke", "label": "Revoke Trakt Authorization"})
    else:
        items.append({"key": "trakt_auth", "label": "Authorize Trakt"})

    win = GIPTVToolsMenu(
        "giptv_tools_menu.xml",
        ADDON_PATH,
        "Default",
        "1080i",
        items=items,
    )
    return win.run()


def _safe_trakt_username():
    try:
        addon = xbmcaddon.Addon()
        username = addon.getSetting("trakt_username")
        return username or "Connected"
    except Exception:
        return "Connected"


def open_context_window(title, items):
    from resources.lib.windows.context_menu import GIPTVContextMenu

    win = GIPTVContextMenu(
        "giptv_context_menu.xml",
        ADDON_PATH,
        "Default",
        "1080i",
        title=title,
        items=items,
    )
    return win.run()
