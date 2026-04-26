# Python 2/3 compatibility for URL parsing
try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

import sys
import os
import json
import base64
import time

sys.path.insert(0, os.getcwd())

import xbmc
import xbmcaddon

import resources.lib.router as router
import resources.utils.giptv as giptv
from resources.lib.manager.index_manager import build_index

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")


def _parse_params():
    try:
        raw = sys.argv[2] if len(sys.argv) > 2 else ""
    except Exception:
        raw = ""

    if raw.startswith("?"):
        raw = raw[1:]

    try:
        return urlparse.parse_qs(raw)
    except Exception:
        return {}


def _get_param(params, key, default=""):
    try:
        return params.get(key, [default])[0]
    except Exception:
        return default


def _is_category_item(item_id):
    return str(item_id).startswith("category:")


def _is_season_item(item_id):
    return str(item_id).startswith("season:")


def _container_update(query):
    xbmc.executebuiltin(
        "Container.Update(plugin://{}/?{})".format(
            ADDON_ID,
            urlparse.urlencode(query),
        )
    )


def _prompt_for_text(heading="Search"):
    keyboard = xbmc.Keyboard("", heading)
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None

    value = keyboard.getText().strip()
    return value or None


def _run_prompted_search(search_mode, heading):
    query = _prompt_for_text(heading)
    if not query:
        return

    _container_update(
        {
            "mode": search_mode,
            "query": query,
            "_": str(int(time.time() * 1000)),
        }
    )


def _handle_cycle_sort(params):
    from resources.lib.manager import sort_manager

    directory_type = _get_param(params, "directory_type")
    directory_id = _get_param(params, "directory_id")

    sort_manager.cycle_sort(directory_type, directory_id)
    new_label = sort_manager.get_sort_label(directory_type, directory_id)

    giptv.notification(ADDON.getAddonInfo("name"), new_label, icon="INFO")

    xbmc.executebuiltin("Container.Refresh")
    xbmc.executebuiltin("AlarmClock(giptv_sorttop,Action(FirstPage),00:00:01,silent)")


def _handle_open_context_window(params):
    item_id = _get_param(params, "item_id")
    name = _get_param(params, "name")
    play_url = _get_param(params, "play_url")
    stream_type = _get_param(params, "stream_type")
    thumb = _get_param(params, "thumb")
    poster = _get_param(params, "poster")
    fanart = _get_param(params, "fanart")
    icon = _get_param(params, "icon")
    plot = _get_param(params, "plot")
    rating = _get_param(params, "rating", "0")
    year = _get_param(params, "year", "0")
    tmdb_id = _get_param(params, "tmdb_id")
    channel_id = _get_param(params, "channel_id")
    epg_channel_id = _get_param(params, "epg_channel_id")
    has_archive = _get_param(params, "has_archive", "0") == "1"

    directory_type = _get_param(params, "directory_type")
    directory_id = _get_param(params, "directory_id")
    refresh_mode = _get_param(params, "refresh_mode")
    category_id = _get_param(params, "category_id")
    category_name = _get_param(params, "category_name", name)
    search_query = _get_param(params, "search_query")
    page = _get_param(params, "page", "1")

    season = _get_param(params, "season")
    episode = _get_param(params, "episode")

    favourite_kind = _get_param(params, "favourite_kind", "playable")
    target_mode = _get_param(params, "target_mode")
    series_id = _get_param(params, "series_id")
    series_name = _get_param(params, "series_name", name)
    season_num = _get_param(params, "season_num", season)

    is_category = _is_category_item(item_id)
    is_season = _is_season_item(item_id)
    is_series_folder = stream_type == "series" and not play_url and not is_season
    is_folder_item = is_category or is_season or is_series_folder
    is_playable_item = not is_folder_item

    from resources.lib.manager import favourites_manager, sort_manager

    sort_label = (
        sort_manager.get_sort_label(directory_type, directory_id)
        if directory_type
        else ""
    )

    if not favourite_kind:
        if is_season:
            favourite_kind = "season_folder"
        elif is_series_folder:
            favourite_kind = "series_folder"
        else:
            favourite_kind = "playable"

    if not target_mode:
        if favourite_kind == "series_folder":
            target_mode = "list_series_seasons"
        elif favourite_kind == "season_folder":
            target_mode = "list_series_episodes"
        else:
            target_mode = "play_stream"

    if not series_id and is_series_folder:
        series_id = item_id
    elif not series_id and is_season:
        parts = str(item_id).split(":", 2)
        if len(parts) == 3:
            _, parsed_series_id, parsed_season_num = parts
            series_id = parsed_series_id
            if not season_num:
                season_num = parsed_season_num

    items = []

    if has_archive:
        items.append({"key": "catchup", "label": "Catch-up"})

    if refresh_mode == "list_categories":
        items.append({"key": "filter_directory", "label": "Filter"})
    elif refresh_mode == "list_streams":
        items.append({"key": "filter_directory", "label": "Filter"})
    elif refresh_mode == "list_series_streams":
        items.append({"key": "filter_directory", "label": "Filter"})

    if stream_type == "live":
        items.append({"key": "global_search_directory", "label": "Search ALL Live TV"})
    elif stream_type == "vod":
        items.append({"key": "global_search_directory", "label": "Search ALL Movies"})
    elif stream_type == "series":
        items.append(
            {"key": "global_search_directory", "label": "Search ALL TV Series"}
        )

    if sort_label:
        items.append({"key": "cycle_sort", "label": sort_label})

    giptv.log(
        "[TRAKT CTX] name={} stream_type={} tmdb_id={} season={} episode={}".format(
            name, stream_type, tmdb_id, season, episode
        ),
        xbmc.LOGINFO,
    )

    favourite_target = is_playable_item or is_series_folder or is_season
    if favourite_target:
        if favourites_manager.is_favourite(item_id):
            items.append({"key": "remove_favourite", "label": "Remove from Favourites"})
        else:
            items.append({"key": "add_favourite", "label": "Add to Favourites"})

    try:
        from resources.apis import trakt_api

        valid_tmdb_id = str(tmdb_id or "").isdigit()
        giptv.log(
            "[TRAKT CTX] authenticated={} valid_tmdb_id={}".format(
                trakt_api.trakt_is_authenticated(), valid_tmdb_id
            ),
            xbmc.LOGINFO,
        )

        if trakt_api.trakt_is_authenticated() and valid_tmdb_id:
            if stream_type == "vod":
                items.append(
                    {"key": "trakt_mark_watched", "label": "Mark Watched on Trakt"}
                )
                items.append(
                    {
                        "key": "trakt_unmark_watched",
                        "label": "Mark Unwatched on Trakt",
                    }
                )

            elif stream_type == "series":
                if season and episode:
                    items.append(
                        {"key": "trakt_mark_watched", "label": "Mark Episode Watched"}
                    )
                    items.append(
                        {
                            "key": "trakt_unmark_watched",
                            "label": "Mark Episode Unwatched",
                        }
                    )
                elif season or season_num:
                    items.append(
                        {"key": "trakt_mark_watched", "label": "Mark Season Watched"}
                    )
                    items.append(
                        {
                            "key": "trakt_unmark_watched",
                            "label": "Mark Season Unwatched",
                        }
                    )
                elif is_series_folder:
                    items.append(
                        {"key": "trakt_mark_watched", "label": "Mark Series Watched"}
                    )
                    items.append(
                        {
                            "key": "trakt_unmark_watched",
                            "label": "Mark Series Unwatched",
                        }
                    )
    except Exception:
        pass

    items.extend(
        [
            {"key": "open_favourites", "label": "Open Favourites"},
            {"key": "open_watched", "label": "Open Recently Watched"},
            {"key": "open_tools", "label": "Open Tools Menu"},
            {"key": "open_settings", "label": "Open Settings"},
        ]
    )

    choice = giptv.open_context_window(name or "GIPTV Menu", items)
    xbmc.sleep(100)

    if not choice:
        return

    if choice == "cycle_sort":
        sort_params = {
            "directory_type": [directory_type],
            "directory_id": [directory_id],
            "refresh_mode": [refresh_mode],
            "stream_type": [stream_type],
            "category_id": [category_id],
            "name": [category_name if is_category else name],
            "search_query": [search_query],
        }
        _handle_cycle_sort(sort_params)
        return

    if choice == "filter_directory":
        if refresh_mode == "list_categories":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=prompt_filter_categories&stream_type={})".format(
                    ADDON_ID,
                    urlparse.quote(stream_type, safe=""),
                )
            )
            return

        if refresh_mode == "list_streams":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=prompt_filter_streams&stream_type={}&category_id={}&name={})".format(
                    ADDON_ID,
                    urlparse.quote(stream_type, safe=""),
                    urlparse.quote(category_id, safe=""),
                    urlparse.quote(category_name or name, safe=""),
                )
            )
            return

        if refresh_mode == "list_series_streams":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=prompt_filter_series&stream_type={}&category_id={}&name={})".format(
                    ADDON_ID,
                    urlparse.quote(stream_type, safe=""),
                    urlparse.quote(category_id, safe=""),
                    urlparse.quote(category_name or name, safe=""),
                )
            )
            return

    if choice == "global_search_directory":
        if stream_type == "live":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=run_global_live_search)".format(ADDON_ID)
            )
            return
        if stream_type == "vod":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=run_global_vod_search)".format(ADDON_ID)
            )
            return
        if stream_type == "series":
            xbmc.executebuiltin(
                "RunPlugin(plugin://{}/?action=run_global_series_search)".format(
                    ADDON_ID
                )
            )
            return

    if choice == "open":
        if is_season:
            parts = str(item_id).split(":", 2)
            if len(parts) == 3:
                _, parsed_series_id, parsed_season_num = parts
                _container_update(
                    {
                        "mode": "list_series_episodes",
                        "series_id": parsed_series_id,
                        "season_num": parsed_season_num,
                        "series_name": category_name or series_name or name,
                    }
                )
            return

        if is_series_folder:
            _container_update(
                {
                    "mode": "list_series_seasons",
                    "series_id": series_id or item_id,
                    "series_name": series_name or name,
                }
            )
            return

        if stream_type == "series":
            _container_update(
                {
                    "mode": "list_series_streams",
                    "stream_type": stream_type,
                    "category_id": category_id,
                    "name": category_name,
                    "page": page or "1",
                    "search_query": search_query or "",
                }
            )
        else:
            _container_update(
                {
                    "mode": "list_streams",
                    "stream_type": stream_type,
                    "category_id": category_id,
                    "name": category_name,
                    "page": page or "1",
                    "search_query": search_query or "",
                }
            )
        return

    if choice == "play":
        metadata = {
            "thumb": thumb or "",
            "poster": poster or "",
            "fanart": fanart or "",
            "icon": icon or "",
            "plot": plot or "",
            "rating": rating or "0",
            "year": year or "0",
            "tmdb_id": tmdb_id or "",
            "stream_type": stream_type or "",
            "channel_id": channel_id or "",
            "stream_id": item_id or "",
            "season": season or season_num or "",
            "episode": episode or "",
        }

        try:
            raw = json.dumps(metadata, separators=(",", ":"))
            meta_encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
        except Exception:
            meta_encoded = ""

        xbmc.executebuiltin(
            "PlayMedia(plugin://{}/?mode=play_stream&url={}&name={}&meta={})".format(
                ADDON_ID,
                urlparse.quote(play_url, safe=""),
                urlparse.quote(name, safe=""),
                urlparse.quote(meta_encoded, safe=""),
            )
        )
        return

    if choice == "catchup":
        _container_update(
            {
                "mode": "catchup_dates",
                "stream_id": item_id,
                "channel_id": epg_channel_id or channel_id,
                "name": name,
            }
        )
        return

    if choice == "add_favourite":
        from resources.lib.manager.favourites_manager import add_favourite_from_params

        add_favourite_from_params(
            item_id=item_id,
            title=name,
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
            stream_id=item_id,
            favourite_kind=favourite_kind,
            target_mode=target_mode,
            series_id=series_id,
            series_name=series_name,
            season_num=season_num,
        )

        label = "Added to Favourites"
        if favourite_kind == "series_folder":
            label = "Series added to Favourites"
        elif favourite_kind == "season_folder":
            label = "Season added to Favourites"

        giptv.notification(ADDON.getAddonInfo("name"), label, icon="INFO")
        return

    if choice == "remove_favourite":
        from resources.lib.manager.favourites_manager import (
            remove_favourite_from_params,
        )

        remove_favourite_from_params(item_id=item_id)
        giptv.notification(
            ADDON.getAddonInfo("name"), "Removed from Favourites", icon="INFO"
        )
        return

    if choice in ("trakt_mark_watched", "trakt_unmark_watched"):
        from resources.apis import trakt_api

        is_mark = choice == "trakt_mark_watched"
        season_value = season or season_num
        ok = False

        if stream_type == "vod":
            ok = (
                trakt_api.trakt_mark_movie_watched(tmdb_id)
                if is_mark
                else trakt_api.trakt_unmark_movie_watched(tmdb_id)
            )

        elif stream_type == "series" and season and episode:
            ok = (
                trakt_api.trakt_mark_episode_watched(tmdb_id, season, episode)
                if is_mark
                else trakt_api.trakt_unmark_episode_watched(tmdb_id, season, episode)
            )

        elif stream_type == "series" and season_value:
            fn_name = (
                "trakt_mark_season_watched"
                if is_mark
                else "trakt_unmark_season_watched"
            )
            fn = getattr(trakt_api, fn_name, None)
            if fn:
                ok = fn(tmdb_id, season_value)

        elif stream_type == "series":
            ok = (
                trakt_api.trakt_mark_show_watched(tmdb_id)
                if is_mark
                else trakt_api.trakt_unmark_show_watched(tmdb_id)
            )

        if ok:
            giptv.safe_refresh_container()
        else:
            action_text = "mark as watched" if is_mark else "unmark as watched"
            giptv.notification(
                ADDON.getAddonInfo("name"),
                "Failed to {} on Trakt.".format(action_text),
                icon="ERROR",
            )
        return

    if choice == "open_tools":
        _handle_action("open_tools_window", params)
        return

    if choice == "open_settings":
        giptv.open_settings()
        return

    if choice == "open_favourites":
        _container_update(
            {
                "mode": "favourites",
                "_": str(int(time.time() * 1000)),
            }
        )
        return

    if choice == "open_watched":
        _container_update(
            {
                "mode": "recently_watched",
                "_": str(int(time.time() * 1000)),
            }
        )
        return


def _handle_open_tools_window():
    choice = giptv.open_tools_window()
    if not choice:
        return

    xbmc.executebuiltin(f"RunPlugin(plugin://{ADDON_ID}/?action={choice})")


def _handle_prompt_filter_categories(params):
    stream_type = _get_param(params, "stream_type")
    query = _prompt_for_text("Filter")
    if not query:
        return

    xbmc.executebuiltin(
        "Container.Update(plugin://{}/?mode=list_categories&stream_type={}&search_query={}&page=1&_={})".format(
            ADDON_ID,
            urlparse.quote(stream_type, safe=""),
            urlparse.quote(query, safe=""),
            str(int(time.time() * 1000)),
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")


def _handle_prompt_filter_streams(params):
    stream_type = _get_param(params, "stream_type")
    category_id = _get_param(params, "category_id")
    name = _get_param(params, "name")
    query = _prompt_for_text("Filter")
    if not query:
        return

    xbmc.executebuiltin(
        "Container.Update(plugin://{}/?mode=list_streams&stream_type={}&category_id={}&name={}&search_query={}&page=1&_={})".format(
            ADDON_ID,
            urlparse.quote(stream_type, safe=""),
            urlparse.quote(category_id, safe=""),
            urlparse.quote(name, safe=""),
            urlparse.quote(query, safe=""),
            str(int(time.time() * 1000)),
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")


def _handle_prompt_filter_series(params):
    stream_type = _get_param(params, "stream_type")
    category_id = _get_param(params, "category_id")
    name = _get_param(params, "name")
    query = _prompt_for_text("Filter")
    if not query:
        return

    xbmc.executebuiltin(
        "Container.Update(plugin://{}/?mode=list_series_streams&stream_type={}&category_id={}&name={}&search_query={}&page=1&_={})".format(
            ADDON_ID,
            urlparse.quote(stream_type, safe=""),
            urlparse.quote(category_id, safe=""),
            urlparse.quote(name, safe=""),
            urlparse.quote(query, safe=""),
            str(int(time.time() * 1000)),
        )
    )
    xbmc.executebuiltin("AlarmClock(giptv_filtertop,Action(FirstPage),00:00:01,silent)")


def _handle_action(action, params):
    if action == "close_settings":
        giptv.close_setting()
        return True

    if action == "cycle_sort":
        _handle_cycle_sort(params)
        return True

    if action == "donate":
        giptv.donate()
        return True

    if action == "clear_cache":
        giptv.clear_cache()
        return True

    if action == "build_search_index":
        giptv.notification(
            ADDON.getAddonInfo("name"),
            "Building Search Index may take ~2 minutes initially",
        )
        build_index(notify=True, source="manual_build_search_index", force=False)
        return True

    if action == "build_search_index_refresh":
        xbmc.executebuiltin("Container.Refresh")
        build_index(notify=True, source="manual_build_search_index_refresh", force=True)
        return True

    if action == "clear_history":
        from resources.lib.manager.history_manager import clear_history

        clear_history()
        giptv.notification(
            ADDON.getAddonInfo("name"), "Recently Watched Reset Done", icon="INFO"
        )
        xbmc.executebuiltin("Container.Refresh")
        return True

    if action == "open_settings":
        giptv.open_settings()
        return True

    if action == "trakt_auth":
        from resources.apis import trakt_api

        trakt_api.trakt_authenticate()
        return True

    if action == "trakt_revoke":
        from resources.apis import trakt_api

        trakt_api.trakt_revoke_auth()
        return True

    if action == "trakt_status":
        from resources.apis import trakt_api

        username = trakt_api.trakt_get_username() or "Connected"
        giptv.notification(
            ADDON.getAddonInfo("name"), f"Trakt connected: {username}", icon="INFO"
        )
        return True

    if action == "trakt_auth_test":
        from resources.apis import trakt_api

        me = trakt_api.trakt_get_me()
        if me and me.get("username"):
            giptv.notification(
                ADDON.getAddonInfo("name"), f"Trakt OK: {me['username']}", icon="INFO"
            )
        else:
            giptv.notification(
                ADDON.getAddonInfo("name"), "Trakt check failed", icon="ERROR"
            )
        return True

    if action == "clear_epg_url":
        selected = ADDON.getSetting("account")

        if selected == "1":
            ADDON.setSetting("epg_url1", "")
        elif selected == "2":
            ADDON.setSetting("epg_url2", "")
        else:
            ADDON.setSetting("epg_url", "")

        xbmc.executebuiltin("Container.Refresh")
        return True

    if action == "open_context_window":
        _handle_open_context_window(params)
        return True

    if action == "open_tools_window":
        _handle_open_tools_window()
        return True

    if action == "run_global_search":
        _run_prompted_search("global_search", "Global Search")
        return True

    if action == "run_global_live_search":
        _run_prompted_search("global_live_search", "Search ALL Live TV")
        return True

    if action == "run_global_vod_search":
        _run_prompted_search("global_vod_search", "Search ALL Movies")
        return True

    if action == "run_global_series_search":
        _run_prompted_search("global_series_search", "Search ALL TV Series")
        return True

    if action == "prompt_filter_categories":
        _handle_prompt_filter_categories(params)
        return True

    if action == "prompt_filter_streams":
        _handle_prompt_filter_streams(params)
        return True

    if action == "prompt_filter_series":
        _handle_prompt_filter_series(params)
        return True

    return False


if __name__ == "__main__":
    params = _parse_params()
    action = params.get("action", [None])[0]

    if not _handle_action(action, params):
        router.handle_routing(params)
