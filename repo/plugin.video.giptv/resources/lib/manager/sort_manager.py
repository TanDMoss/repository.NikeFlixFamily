# -*- coding: utf-8 -*-
import json
import xbmcaddon
import xbmcvfs


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")

SORT_FILE = xbmcvfs.translatePath(
    f"special://profile/addon_data/{ADDON_ID}/sort_state.json"
)

LIVE_SORTS = [
    ("az", "Sort: A → Z"),
    ("za", "Sort: Z → A"),
    ("", "Sort: Default"),
]

STREAM_SORTS = [
    ("az", "Sort: A → Z"),
    ("za", "Sort: Z → A"),
    ("", "Sort: Default"),
]

CATEGORY_SORTS = [
    ("az", "Sort: A → Z"),
    ("za", "Sort: Z → A"),
    ("", "Sort: Default"),
]

FAVOURITES_SORTS = [
    ("recent", "Sort: Recently Added"),
    ("oldest", "Sort: Oldest Added"),
    ("az", "Sort: A → Z"),
    ("za", "Sort: Z → A"),
    ("", "Sort: Default"),
]


def _read_state():
    if not xbmcvfs.exists(SORT_FILE):
        return {}

    try:
        f = xbmcvfs.File(SORT_FILE, "r")
        try:
            raw = f.read()
        finally:
            f.close()

        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _write_state(data):
    try:
        f = xbmcvfs.File(SORT_FILE, "w")
        try:
            f.write(json.dumps(data))
        finally:
            f.close()
    except Exception:
        pass


def get_sort_options(directory_type):
    if directory_type == "favourites":
        return FAVOURITES_SORTS
    if directory_type == "categories":
        return CATEGORY_SORTS
    if directory_type == "streams":
        return STREAM_SORTS
    return LIVE_SORTS


def get_sort_list(directory_type):
    return get_sort_options(directory_type)


def get_sort_key(directory_type, directory_id=""):
    return f"{directory_type}:{directory_id or 'root'}"


def get_current_sort(directory_type, directory_id=""):
    state = _read_state()
    key = get_sort_key(directory_type, directory_id)
    return state.get(key, "")


def set_current_sort(directory_type, directory_id="", mode=""):
    state = _read_state()
    key = get_sort_key(directory_type, directory_id)
    state[key] = mode
    _write_state(state)


def set_sort(directory_type, directory_id="", mode=""):
    set_current_sort(directory_type, directory_id, mode)


def cycle_sort(directory_type, directory_id=""):
    sorts = get_sort_list(directory_type)
    current = get_current_sort(directory_type, directory_id)
    keys = [s[0] for s in sorts]

    try:
        idx = keys.index(current)
        next_idx = (idx + 1) % len(keys)
    except ValueError:
        next_idx = 0

    new_mode = keys[next_idx]
    set_sort(directory_type, directory_id, new_mode)
    return new_mode


def get_sort_label(directory_type, directory_id=""):
    mode = get_current_sort(directory_type, directory_id)

    for key, label in get_sort_list(directory_type):
        if key == mode:
            return label

    return "Sort: Default"
