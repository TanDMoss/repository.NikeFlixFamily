# -*- coding: utf-8 -*-
import sys
import time
import threading
import urllib.parse
import urllib.request
import socket

from resources.utils import giptv, settings
import xbmc

try:
    from http.server import BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    from http.server import HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn


MAX_PROXY_CLIENTS = 6
_CLIENT_SEMAPHORE = threading.Semaphore(MAX_PROXY_CLIENTS)


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, proxy_config=None):
        self.proxy_config = proxy_config or {}
        HTTPServer.__init__(self, server_address, RequestHandlerClass)

    def handle_error(self, request, client_address):
        exc_type, exc, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError):
            giptv.log(f"Client disconnected: {client_address}", xbmc.LOGINFO)
            return
        HTTPServer.handle_error(self, request, client_address)


class StreamProxyHandler(BaseHTTPRequestHandler):
    """
    GET /stream?u=<url-encoded-upstream-url>
    Streams bytes from upstream to Kodi and reconnects on stall/failure.
    """

    HEADER_PROFILES = [
        {
            "User-Agent": "VLC/3.0.20 LibVLC/3.0.20",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        },
        {
            "User-Agent": "mpv/0.35.0",
            "Accept": "*/*",
            "Connection": "keep-alive",
        },
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        },
        {
            "User-Agent": "Kodi/21.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "*/*",
            "Connection": "keep-alive",
        },
    ]

    server_version = "KodiIPTVProxy/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        giptv.log((fmt % args), xbmc.LOGINFO)

    def _get_proxy_config(self):
        cfg = getattr(self.server, "proxy_config", {}) or {}
        return {
            "read_chunk_size": int(cfg.get("read_chunk_size", 64 * 1024)),
            "upstream_timeout": int(cfg.get("upstream_timeout", 10)),
            "stall_threshold": float(cfg.get("stall_threshold", 8.0)),
            "reconnect_delay": float(cfg.get("reconnect_delay", 0.5)),
            "max_reconnect_attempts": int(cfg.get("max_reconnect_attempts", 10)),
            "flush_interval": int(cfg.get("flush_interval", 1)),
            "sleep_on_empty": float(cfg.get("sleep_on_empty", 0.08)),
            "profile_name": str(cfg.get("profile_name", "medium")),
        }

    def do_GET(self):
        acquired = _CLIENT_SEMAPHORE.acquire(False)
        if not acquired:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(b"Proxy busy")
            except Exception:
                pass
            return

        try:
            self._do_get_impl()
        finally:
            _CLIENT_SEMAPHORE.release()

    def _do_get_impl(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/stream":
            self.send_response(404)
            self.send_header("Connection", "close")
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        upstream_list = qs.get("u") or []
        if not upstream_list:
            self.send_response(400)
            self.send_header("Connection", "close")
            self.end_headers()
            return

        upstream_url = urllib.parse.unquote(upstream_list[0])
        cfg = self._get_proxy_config()

        read_chunk_size = cfg["read_chunk_size"]
        upstream_timeout = cfg["upstream_timeout"]
        stall_threshold = cfg["stall_threshold"]
        reconnect_delay = cfg["reconnect_delay"]
        max_reconnect_attempts = cfg["max_reconnect_attempts"]
        flush_interval = cfg["flush_interval"]
        sleep_on_empty = cfg["sleep_on_empty"]
        profile_name = cfg["profile_name"]

        giptv.log(
            f"Start stream -> {upstream_url} | "
            f"profile={profile_name} | "
            f"chunk={read_chunk_size // 1024}KB | "
            f"stall={stall_threshold}s",
            xbmc.LOGINFO,
        )

        monitor = xbmc.Monitor()
        reconnect_attempts = 0
        headers_sent = False

        url_lower = upstream_url.lower()
        is_hls = ".m3u8" in url_lower
        is_catchup = "/timeshift/" in url_lower
        is_live = "/live/" in url_lower and not is_catchup
        is_live_like = is_hls or is_live

        while (
            not monitor.abortRequested() and reconnect_attempts < max_reconnect_attempts
        ):
            resp = None
            try:
                headers = self.HEADER_PROFILES[
                    reconnect_attempts % len(self.HEADER_PROFILES)
                ].copy()

                client_range = self.headers.get("Range")
                if client_range and not is_live_like:
                    headers["Range"] = client_range

                giptv.log(
                    f"Proxy request -> url={upstream_url} | "
                    f"client_range={client_range} | "
                    f"is_live_like={is_live_like} | "
                    f"is_catchup={is_catchup}",
                    xbmc.LOGINFO,
                )

                req = urllib.request.Request(upstream_url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=upstream_timeout)

                status_code = getattr(resp, "status", 200)

                upstream_content_type = resp.headers.get("Content-Type", "")
                upstream_content_length = resp.headers.get("Content-Length")
                upstream_accept_ranges = resp.headers.get("Accept-Ranges")
                upstream_content_range = resp.headers.get("Content-Range")

                giptv.log(
                    "Upstream response: "
                    f"status={status_code} "
                    f"content-length={upstream_content_length} "
                    f"accept-ranges={upstream_accept_ranges} "
                    f"content-range={upstream_content_range}",
                    xbmc.LOGINFO,
                )

                if not upstream_content_type:
                    path = urllib.parse.urlparse(upstream_url.lower()).path
                    if path.endswith(".m3u8"):
                        upstream_content_type = "application/vnd.apple.mpegurl"
                    elif path.endswith(".mp4"):
                        upstream_content_type = "video/mp4"
                    elif path.endswith(".mkv"):
                        upstream_content_type = "video/x-matroska"
                    elif path.endswith(".ts"):
                        upstream_content_type = "video/MP2T"
                    else:
                        upstream_content_type = "application/octet-stream"

                if not headers_sent:
                    self.send_response(status_code)
                    self.send_header("Content-Type", upstream_content_type)

                    if upstream_content_range:
                        self.send_header("Content-Range", upstream_content_range)
                        self.send_header("Accept-Ranges", "bytes")
                    elif (
                        upstream_accept_ranges
                        and upstream_accept_ranges.lower() == "bytes"
                    ):
                        self.send_header("Accept-Ranges", "bytes")

                    if upstream_content_length:
                        self.send_header("Content-Length", upstream_content_length)

                    self.send_header("Connection", "close")
                    self.end_headers()
                    headers_sent = True

                reconnect_attempts = 0
                last_active = time.monotonic()
                write_count = 0

                while not monitor.abortRequested():
                    chunk = resp.read(read_chunk_size)

                    if chunk:
                        try:
                            self.wfile.write(chunk)
                            write_count += 1

                            if write_count >= flush_interval:
                                self.wfile.flush()
                                write_count = 0

                            last_active = time.monotonic()
                        except (
                            BrokenPipeError,
                            ConnectionResetError,
                            OSError,
                            socket.error,
                        ):
                            giptv.log("Kodi stopped playing.", xbmc.LOGINFO)
                            return
                    else:
                        if is_live_like:
                            if time.monotonic() - last_active > stall_threshold:
                                giptv.log(
                                    "Stream stalled. Reconnecting...", xbmc.LOGWARNING
                                )
                                break
                            time.sleep(sleep_on_empty)
                            continue

                        try:
                            self.wfile.flush()
                        except Exception:
                            pass
                        return

            except Exception as e:
                reconnect_attempts += 1
                giptv.log(
                    f"Connection lost ({reconnect_attempts}/{max_reconnect_attempts}): {e}",
                    xbmc.LOGWARNING,
                )

                if not headers_sent:
                    try:
                        self.send_response(502)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(str(e).encode("utf-8", "ignore"))
                    except Exception:
                        pass
                    return

                time.sleep(reconnect_delay)

            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass

        giptv.log("Stream session ended.", xbmc.LOGINFO)


class IPTVStreamProxy(object):
    def __init__(self, addon, host="127.0.0.1", port=0):
        self.addon = addon
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None
        self._last_buffer = None

    def _build_proxy_config(self):
        buffer_kb = settings.get_buffer_size(self.addon)
        profile_name = settings.get_buffer_size_label(self.addon)

        preset_map = {
            64: {
                "profile_name": "small",
                "read_chunk_size": 64 * 1024,
                "upstream_timeout": 8,
                "stall_threshold": 10.0,
                "reconnect_delay": 0.30,
                "max_reconnect_attempts": 8,
                "flush_interval": 4,
                "sleep_on_empty": 0.05,
            },
            128: {
                "profile_name": "medium",
                "read_chunk_size": 64 * 1024,
                "upstream_timeout": 10,
                "stall_threshold": 12.0,
                "reconnect_delay": 0.45,
                "max_reconnect_attempts": 10,
                "flush_interval": 4,
                "sleep_on_empty": 0.08,
            },
            256: {
                "profile_name": "large",
                "read_chunk_size": 128 * 1024,
                "upstream_timeout": 12,
                "stall_threshold": 16.0,
                "reconnect_delay": 0.65,
                "max_reconnect_attempts": 12,
                "flush_interval": 6,
                "sleep_on_empty": 0.10,
            },
            512: {
                "profile_name": "very_large",
                "read_chunk_size": 128 * 1024,
                "upstream_timeout": 15,
                "stall_threshold": 20.0,
                "reconnect_delay": 0.90,
                "max_reconnect_attempts": 15,
                "flush_interval": 8,
                "sleep_on_empty": 0.12,
            },
        }

        cfg = preset_map.get(buffer_kb, preset_map[128]).copy()

        if profile_name:
            cfg["profile_name"] = profile_name

        return cfg

    def start(self):
        if self._httpd:
            return self.port

        proxy_config = self._build_proxy_config()

        self._httpd = _ThreadingHTTPServer(
            (self.host, self.port),
            StreamProxyHandler,
            proxy_config=proxy_config,
        )
        self.port = self._httpd.server_address[1]

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="IPTVStreamProxy",
        )
        self._thread.daemon = True
        self._thread.start()

        giptv.log(
            f"Listening on http://{self.host}:{self.port} | "
            f"profile={proxy_config['profile_name']} | "
            f"chunk={proxy_config['read_chunk_size'] // 1024}KB | "
            f"stall={proxy_config['stall_threshold']}s | "
            f"timeout={proxy_config['upstream_timeout']}s",
            xbmc.LOGINFO,
        )
        return self.port

    def stop(self):
        if not self._httpd:
            return

        httpd = self._httpd
        thread = self._thread

        self._httpd = None
        self._thread = None

        try:
            httpd.shutdown()
        except Exception:
            pass

        try:
            httpd.server_close()
        except Exception:
            pass

        if thread and thread.is_alive():
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass

        giptv.log("Stopped", xbmc.LOGINFO)
