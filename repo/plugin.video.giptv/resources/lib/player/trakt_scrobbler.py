# -*- coding: utf-8 -*-
import json
import xbmc
import xbmcgui

from resources.utils import giptv
from resources.apis import trakt_api

_PLAYBACK_PROP = "giptv.trakt.playback"
_COMPLETE_PROGRESS = 95.0


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _set_playback_data(data):
    try:
        xbmcgui.Window(10000).setProperty(_PLAYBACK_PROP, json.dumps(data or {}))
    except Exception:
        pass


def get_current_playback():
    try:
        raw = xbmcgui.Window(10000).getProperty(_PLAYBACK_PROP)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def set_current_playback(metadata):
    meta = metadata or {}
    data = {
        "started": False,
        "last_action": None,
        "resume_applied": False,
        "stop_handled": False,
        "last_known_time": 0.0,
        "last_known_total": 0.0,
        "last_known_progress": 0.0,
        **meta,
    }
    _set_playback_data(data)


def clear_current_playback():
    try:
        xbmcgui.Window(10000).clearProperty(_PLAYBACK_PROP)
    except Exception:
        pass


def _update_current_playback(**updates):
    data = get_current_playback() or {}
    data.update(updates)
    _set_playback_data(data)


def _get_time_pair(player):
    try:
        current = float(player.getTime())
    except Exception:
        current = 0.0

    try:
        total = float(player.getTotalTime())
    except Exception:
        total = 0.0

    return current, total


def _get_progress(player):
    try:
        current, total = _get_time_pair(player)

        if total <= 0 or current <= 0:
            return 0.0

        return max(0.0, min(100.0, (current / total) * 100.0))
    except Exception:
        return 0.0


def _calculate_progress(current_time, total_time):
    current_time = _safe_float(current_time, 0.0)
    total_time = _safe_float(total_time, 0.0)

    if total_time <= 0 or current_time <= 0:
        return 0.0

    return max(0.0, min(100.0, (current_time / total_time) * 100.0))


def _calculate_resume_seconds_from_progress(total_time, resume_progress):
    total_time = _safe_float(total_time, 0.0)
    resume_progress = _safe_float(resume_progress, 0.0)

    if total_time <= 0 or resume_progress <= 0.0:
        return 0

    return int((resume_progress / 100.0) * total_time)


def _scrobble_from_meta(meta, action, progress):
    stream_type = meta.get("stream_type")
    tmdb_id = meta.get("tmdb_id")
    season = meta.get("season")
    episode = meta.get("episode")
    progress = _safe_float(progress, 0.0)

    giptv.log(
        f"[TRAKT SCROBBLE] action={action} stream_type={stream_type} "
        f"tmdb_id={tmdb_id} season={season} episode={episode} progress={progress}",
        xbmc.LOGINFO,
    )

    if not tmdb_id:
        return False

    if stream_type == "vod":
        return trakt_api.trakt_scrobble_movie(action, tmdb_id, progress)

    if stream_type == "series":
        return trakt_api.trakt_scrobble_episode(
            action,
            tmdb_id,
            season,
            episode,
            progress,
        )

    return False


def _scrobble(action, progress):
    meta = get_current_playback() or {}
    return _scrobble_from_meta(meta, action, progress)


def _save_resume_point(player=None, force_progress=None):
    meta = get_current_playback() or {}
    stream_type = meta.get("stream_type")
    tmdb_id = meta.get("tmdb_id")
    season = meta.get("season")
    episode = meta.get("episode")

    if not tmdb_id:
        return False

    current_time = 0.0
    total_time = 0.0
    progress = 0.0

    if player is not None:
        current_time, total_time = _get_time_pair(player)
        progress = _get_progress(player)

    if current_time <= 0:
        current_time = _safe_float(meta.get("last_known_time"), 0.0)

    if total_time <= 0:
        total_time = _safe_float(meta.get("last_known_total"), 0.0)

    if force_progress is not None:
        progress = _safe_float(force_progress, progress)

    if progress <= 0.0 and total_time > 0 and current_time > 0:
        progress = _calculate_progress(current_time, total_time)

    progress = max(0.0, min(100.0, _safe_float(progress, 0.0)))

    _update_current_playback(
        last_known_time=current_time,
        last_known_total=total_time,
        last_known_progress=progress,
    )

    if current_time < 30 and progress < 1.0:
        return False

    if total_time <= 0 or current_time <= 0:
        return False

    if progress < 1.0:
        return False

    if progress >= _COMPLETE_PROGRESS:
        return False

    if stream_type == "vod":
        return trakt_api.trakt_save_movie_progress(
            tmdb_id,
            progress,
            current_time=current_time,
            total_time=total_time,
        )

    if stream_type == "series" and season and episode:
        return trakt_api.trakt_save_episode_progress(
            tmdb_id,
            season,
            episode,
            progress,
            current_time=current_time,
            total_time=total_time,
        )

    return False


def _clear_resume_point(meta):
    stream_type = meta.get("stream_type")
    tmdb_id = meta.get("tmdb_id")
    season = meta.get("season")
    episode = meta.get("episode")

    if not tmdb_id:
        return False

    if stream_type == "vod":
        return trakt_api.trakt_clear_movie_playback(tmdb_id)

    if stream_type == "series" and season and episode:
        return trakt_api.trakt_clear_episode_playback(tmdb_id, season, episode)

    return False


def _mark_watched_from_meta(meta, progress):
    stream_type = meta.get("stream_type")
    tmdb_id = meta.get("tmdb_id")
    season = meta.get("season")
    episode = meta.get("episode")
    progress = _safe_float(progress, 0.0)

    if progress < _COMPLETE_PROGRESS:
        return False

    if not tmdb_id:
        return False

    giptv.log(
        f"[TRAKT COMPLETE] stream_type={stream_type} tmdb_id={tmdb_id} "
        f"season={season} episode={episode} progress={progress}",
        xbmc.LOGINFO,
    )

    if meta.get("started"):
        _scrobble_from_meta(meta, "stop", progress)

    if stream_type == "vod":
        trakt_api.trakt_mark_movie_watched(tmdb_id)
        _clear_resume_point(meta)
        return True

    if stream_type == "series" and season and episode:
        trakt_api.trakt_mark_episode_watched(tmdb_id, season, episode)
        _clear_resume_point(meta)
        return True

    return False


def stop_and_clear_current_playback(reason="manual_clear"):
    meta = get_current_playback() or {}

    if not meta:
        clear_current_playback()
        return

    try:
        started = bool(meta.get("started"))
        progress = _safe_float(meta.get("last_known_progress"), 0.0)

        giptv.log(
            f"[TRAKT SCROBBLER] force stop reason={reason} progress={progress} "
            f"stream_type={meta.get('stream_type')} tmdb_id={meta.get('tmdb_id')}",
            xbmc.LOGINFO,
        )

        if progress >= _COMPLETE_PROGRESS:
            _mark_watched_from_meta(meta, progress)
        else:
            if progress >= 1.0:
                _save_resume_point(player=None, force_progress=progress)

            if started and progress >= 0.5:
                _scrobble_from_meta(meta, "stop", progress)

    except Exception as e:
        giptv.log(f"[TRAKT SCROBBLER] force stop failed: {e}", xbmc.LOGWARNING)

    clear_current_playback()


class TraktPlayer(xbmc.Player):
    def onAVStarted(self):
        meta = get_current_playback() or {}

        if not meta:
            return

        resume_applied = bool(meta.get("resume_applied"))
        resume_seconds = int(_safe_float(meta.get("resume_seconds"), 0))
        resume_progress = _safe_float(meta.get("resume_progress"), 0.0)

        if not resume_applied:
            try:
                total_wait_ms = 0
                total_time = 0.0

                while total_wait_ms < 6000:
                    total_time = _safe_float(self.getTotalTime(), 0.0)

                    if total_time > 0:
                        break

                    xbmc.sleep(250)
                    total_wait_ms += 250

                seek_to = 0

                if resume_seconds > 0:
                    seek_to = resume_seconds
                elif resume_progress > 0.0 and total_time > 0:
                    seek_to = _calculate_resume_seconds_from_progress(
                        total_time,
                        resume_progress,
                    )

                if seek_to > 0:
                    if total_time > 0 and seek_to >= int(total_time) - 10:
                        seek_to = max(0, int(total_time) - 15)

                    self.seekTime(seek_to)

                    calculated_progress = resume_progress

                    if total_time > 0:
                        calculated_progress = _calculate_progress(seek_to, total_time)

                    _update_current_playback(
                        resume_applied=True,
                        last_known_time=float(seek_to),
                        last_known_total=total_time,
                        last_known_progress=calculated_progress,
                    )

                    giptv.log(
                        f"[TRAKT RESUME] seek -> {seek_to}s "
                        f"(resume_seconds={resume_seconds}, "
                        f"resume_progress={resume_progress}, total={total_time})",
                        xbmc.LOGINFO,
                    )

            except Exception as e:
                giptv.log(f"[TRAKT RESUME] seek failed: {e}", xbmc.LOGWARNING)

        meta = get_current_playback() or meta

        current_time, total_time = _get_time_pair(self)
        progress = _get_progress(self)

        if progress <= 0.0:
            progress = _safe_float(meta.get("last_known_progress"), 0.0)

        if current_time <= 0:
            current_time = _safe_float(meta.get("last_known_time"), 0.0)

        if total_time <= 0:
            total_time = _safe_float(meta.get("last_known_total"), 0.0)

        _update_current_playback(
            last_known_time=current_time,
            last_known_total=total_time,
            last_known_progress=progress,
        )

        if _scrobble("start", progress):
            _update_current_playback(started=True, last_action="start")

    def onPlayBackPaused(self):
        meta = get_current_playback() or {}

        if not meta:
            return

        current_time, total_time = _get_time_pair(self)
        progress = _get_progress(self)

        if progress <= 0.0:
            progress = _safe_float(meta.get("last_known_progress"), 0.0)

        if current_time <= 0:
            current_time = _safe_float(meta.get("last_known_time"), 0.0)

        if total_time <= 0:
            total_time = _safe_float(meta.get("last_known_total"), 0.0)

        _update_current_playback(
            last_known_time=current_time,
            last_known_total=total_time,
            last_known_progress=progress,
        )

        started = bool(meta.get("started"))

        if progress >= _COMPLETE_PROGRESS:
            _mark_watched_from_meta(meta, progress)
            return

        if started and progress >= 1.0:
            if _scrobble("pause", progress):
                _update_current_playback(last_action="pause")

        _save_resume_point(self, force_progress=progress)

    def onPlayBackResumed(self):
        meta = get_current_playback() or {}

        if not meta:
            return

        current_time, total_time = _get_time_pair(self)
        progress = _get_progress(self)

        if progress <= 0.0:
            progress = _safe_float(meta.get("last_known_progress"), 0.0)

        if current_time <= 0:
            current_time = _safe_float(meta.get("last_known_time"), 0.0)

        if total_time <= 0:
            total_time = _safe_float(meta.get("last_known_total"), 0.0)

        _update_current_playback(
            last_known_time=current_time,
            last_known_total=total_time,
            last_known_progress=progress,
        )

        if progress >= 0.5 and progress < _COMPLETE_PROGRESS:
            if _scrobble("start", progress):
                _update_current_playback(started=True, last_action="start")

    def onPlayBackSeek(self, time, seekOffset):
        meta = get_current_playback() or {}

        if not meta:
            return

        try:
            total_time = float(self.getTotalTime())
        except Exception:
            total_time = _safe_float(meta.get("last_known_total"), 0.0)

        seek_time = _safe_float(time, 0.0)

        # Kodi seek callback often gives milliseconds.
        # Convert to seconds when the value is clearly too large.
        if total_time > 0 and seek_time > total_time + 30:
            seek_time = seek_time / 1000.0

        progress = _calculate_progress(seek_time, total_time)

        giptv.log(
            f"[TRAKT SEEK] raw_time={time} seek_time={seek_time} "
            f"total={total_time} progress={progress}",
            xbmc.LOGINFO,
        )

        _update_current_playback(
            last_known_time=seek_time,
            last_known_total=total_time,
            last_known_progress=progress,
        )

    def onPlayBackStopped(self):
        meta = get_current_playback() or {}

        if not meta:
            clear_current_playback()
            return

        if meta.get("stop_handled"):
            clear_current_playback()
            return

        _update_current_playback(stop_handled=True)
        meta = get_current_playback() or meta

        last_known_time = _safe_float(meta.get("last_known_time"), 0.0)
        last_known_total = _safe_float(meta.get("last_known_total"), 0.0)
        last_known_progress = _safe_float(meta.get("last_known_progress"), 0.0)

        current_time = last_known_time
        total_time = last_known_total
        progress = last_known_progress

        try:
            if self.isPlaying():
                fresh_time, fresh_total = _get_time_pair(self)

                if fresh_time > 0 and fresh_total > 0 and fresh_time <= fresh_total + 5:
                    current_time = fresh_time
                    total_time = fresh_total
                    progress = _calculate_progress(current_time, total_time)

        except Exception as e:
            giptv.log(
                f"[TRAKT STOPPED] fresh player read ignored: {e}",
                xbmc.LOGWARNING,
            )

        progress = max(0.0, min(100.0, _safe_float(progress, 0.0)))

        started = bool(meta.get("started"))

        giptv.log(
            f"[TRAKT STOPPED] started={started} progress={progress} "
            f"current={current_time} total={total_time} "
            f"stream_type={meta.get('stream_type')} tmdb_id={meta.get('tmdb_id')}",
            xbmc.LOGINFO,
        )

        _update_current_playback(
            last_known_time=current_time,
            last_known_total=total_time,
            last_known_progress=progress,
        )

        if progress >= _COMPLETE_PROGRESS:
            _mark_watched_from_meta(meta, progress)
            clear_current_playback()
            return

        if started and progress >= 0.5:
            _scrobble_from_meta(meta, "stop", progress)

        _save_resume_point(player=None, force_progress=progress)

        clear_current_playback()

    def onPlayBackEnded(self):
        meta = get_current_playback() or {}

        if not meta:
            clear_current_playback()
            return

        current_time = _safe_float(meta.get("last_known_time"), 0.0)
        total_time = _safe_float(meta.get("last_known_total"), 0.0)
        progress = _safe_float(meta.get("last_known_progress"), 0.0)

        try:
            if self.isPlaying():
                fresh_time, fresh_total = _get_time_pair(self)

                if fresh_time > 0 and fresh_total > 0 and fresh_time <= fresh_total + 5:
                    current_time = fresh_time
                    total_time = fresh_total
                    progress = _calculate_progress(current_time, total_time)

        except Exception as e:
            giptv.log(
                f"[TRAKT ENDED] fresh player read ignored: {e}",
                xbmc.LOGWARNING,
            )

        progress = max(0.0, min(100.0, _safe_float(progress, 0.0)))

        giptv.log(
            f"[TRAKT ENDED CHECK] current={current_time} total={total_time} "
            f"progress={progress}",
            xbmc.LOGINFO,
        )

        if progress >= _COMPLETE_PROGRESS:
            _mark_watched_from_meta(meta, progress)
        else:
            giptv.log(
                f"[TRAKT ENDED IGNORED] progress below complete threshold: {progress}",
                xbmc.LOGWARNING,
            )

            _update_current_playback(
                last_known_time=current_time,
                last_known_total=total_time,
                last_known_progress=progress,
            )

            if progress >= 1.0:
                _save_resume_point(player=None, force_progress=progress)

        clear_current_playback()
