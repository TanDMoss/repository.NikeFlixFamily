# -*- coding: utf-8 -*-
import xbmc

from resources.utils import giptv
from resources.lib.proxy.proxy_instance import stop_proxy


class ProxyPlayer(xbmc.Player):
    def __init__(self):
        super(ProxyPlayer, self).__init__()

    def _current_path(self):
        try:
            return self.getPlayingFile() or ""
        except Exception:
            return ""

    def _is_giptv_proxy_stream(self):
        path = self._current_path().lower()
        return path.startswith("http://127.0.0.1:") and "/stream?u=" in path

    def _safe_stop_proxy(self, reason):
        if not self._is_giptv_proxy_stream():
            giptv.log(
                f"[PROXY_PLAYER] skip stop ({reason}) - current item is not proxy stream",
                xbmc.LOGINFO,
            )
            return

        try:
            stop_proxy()
            giptv.log(f"[PROXY_PLAYER] proxy stopped ({reason})", xbmc.LOGINFO)
        except Exception as e:
            giptv.log(
                f"[PROXY_PLAYER] stop_proxy failed ({reason}): {e}",
                xbmc.LOGWARNING,
            )

    def onPlayBackStopped(self):
        self._safe_stop_proxy("stopped")

    def onPlayBackEnded(self):
        self._safe_stop_proxy("ended")
