# -*- coding: utf-8 -*-
from resources.utils.giptv import make_session
from resources.lib.manager.fetch_manager import cache_handler
from resources.utils.xtream import STATE

import re
import urllib.parse

TMDB_API_KEY = "f090bb54758cabf231fb605d3e3e0468"
BASE_URL = "https://api.themoviedb.org/3/{}"
session = make_session("https://api.themoviedb.org/3")


class TMDbHelper:
    def __init__(self):
        self.image_base_url = "https://image.tmdb.org/t/p/original"

    def _safe_json(self, resp):
        try:
            if not resp:
                return None
            return resp.json()
        except Exception:
            return None

    def _state_prefix(self):
        try:
            return str(getattr(STATE, "username", "") or "default")
        except Exception:
            return "default"

    def _safe_cache_key(self, *parts):
        cleaned = []
        for part in parts:
            value = str(part or "").strip()
            value = value.replace("/", "_").replace(":", "_")
            cleaned.append(value)
        return "_".join(cleaned)

    def _normalize_title(self, title):
        value = str(title or "").strip().lower()

        value = re.sub(r"\s*-\s*\d{4}$", "", value)
        value = re.sub(r"\s*\(\d{4}\)$", "", value)
        value = re.sub(r"\s*\[\d{4}\]$", "", value)

        value = re.sub(r"[^a-z0-9]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _extract_year(self, value):
        value = str(value or "").strip()
        return value if len(value) == 4 and value.isdigit() else ""

    def _full_image(self, path):
        if not path or not self.image_base_url:
            return ""
        if str(path).startswith("http://") or str(path).startswith("https://"):
            return path
        return f"{self.image_base_url}{path}"

    def _build_art(
        self,
        poster_path=None,
        fanart_path=None,
        still_path=None,
        icon_path=None,
        thumb_path=None,
    ):
        art = {}

        poster = self._full_image(poster_path)
        fanart = self._full_image(fanart_path)
        still = self._full_image(still_path)
        icon = self._full_image(icon_path)
        thumb = self._full_image(thumb_path)

        if poster:
            art["poster"] = poster

        if fanart:
            art["fanart"] = fanart

        if still:
            art["still"] = still

        if thumb:
            art["thumb"] = thumb
        elif still:
            art["thumb"] = still
        elif poster:
            art["thumb"] = poster

        if icon:
            art["icon"] = icon
        elif art.get("thumb"):
            art["icon"] = art["thumb"]
        elif poster:
            art["icon"] = poster

        return art

    def _pick_backdrop(self, raw):
        if not raw:
            return ""

        backdrop = raw.get("backdrop_path")
        if backdrop:
            return backdrop

        images = raw.get("images") or {}
        backdrops = images.get("backdrops") or []
        if backdrops:
            return backdrops[0].get("file_path") or ""

        return ""

    def _pick_poster(self, raw):
        if not raw:
            return ""

        poster = raw.get("poster_path")
        if poster:
            return poster

        images = raw.get("images") or {}
        posters = images.get("posters") or []
        if posters:
            return posters[0].get("file_path") or ""

        return ""

    def get_tmdb(self, url):
        try:
            return session.get(url, timeout=20.0)
        except Exception:
            return None

    def _score_search_result(self, result, wanted_title, wanted_year=None, is_tv=False):
        score = 0

        title_key = "name" if is_tv else "title"
        date_key = "first_air_date" if is_tv else "release_date"

        result_title = self._normalize_title(result.get(title_key))
        target_title = self._normalize_title(wanted_title)

        if result_title == target_title:
            score += 100
        elif result_title.startswith(target_title) or target_title.startswith(
            result_title
        ):
            score += 40
        elif target_title and result_title and target_title in result_title:
            score += 20

        result_year = self._extract_year((result.get(date_key) or "")[:4])
        wanted_year = self._extract_year(wanted_year)

        if wanted_year and result_year:
            if wanted_year == result_year:
                score += 30
            else:
                try:
                    diff = abs(int(wanted_year) - int(result_year))
                    if diff == 1:
                        score += 10
                except Exception:
                    pass

        try:
            popularity = float(result.get("popularity") or 0)
            score += min(10, int(popularity // 10))
        except Exception:
            pass

        return score

    def _pick_best_result(self, results, title, year=None, is_tv=False):
        if not results:
            return None

        scored = []
        for result in results:
            scored.append(
                (
                    self._score_search_result(result, title, year, is_tv=is_tv),
                    result,
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]

        if best_score <= 0:
            return None

        return best

    def search_movie_id(self, title, year=None, language="en"):
        if not title:
            return ""

        norm_title = self._normalize_title(title)
        year = self._extract_year(year)

        cache_key = self._safe_cache_key(
            self._state_prefix(), "movie_search", norm_title, year
        )
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return str(cached.get("tmdb_id", ""))

        try:
            query = urllib.parse.quote(title)
            url = (
                "https://api.themoviedb.org/3/search/movie"
                f"?api_key={TMDB_API_KEY}"
                f"&language={language}"
                f"&query={query}"
                "&include_adult=false"
            )
            if year:
                url += f"&year={year}"

            resp = self.get_tmdb(url)
            payload = self._safe_json(resp) or {}
            results = payload.get("results") or []

            best = self._pick_best_result(results, title, year=year, is_tv=False)
            if not best:
                return ""

            tmdb_id = str(best.get("id") or "")
            if tmdb_id:
                cache_handler.set("tmdb_data", cache_key, {"tmdb_id": tmdb_id})
            return tmdb_id
        except Exception:
            return ""

    def search_series_id(self, title, year=None, language="en"):
        if not title:
            return ""

        norm_title = self._normalize_title(title)
        year = self._extract_year(year)

        cache_key = self._safe_cache_key(
            self._state_prefix(), "series_search", norm_title, year
        )
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return str(cached.get("tmdb_id", ""))

        try:
            query = urllib.parse.quote(title)
            url = (
                "https://api.themoviedb.org/3/search/tv"
                f"?api_key={TMDB_API_KEY}"
                f"&language={language}"
                f"&query={query}"
                "&include_adult=false"
            )
            if year:
                url += f"&first_air_date_year={year}"

            resp = self.get_tmdb(url)
            payload = self._safe_json(resp) or {}
            results = payload.get("results") or []

            best = self._pick_best_result(results, title, year=year, is_tv=True)
            if not best:
                return ""

            tmdb_id = str(best.get("id") or "")
            if tmdb_id:
                cache_handler.set("tmdb_data", cache_key, {"tmdb_id": tmdb_id})
            return tmdb_id
        except Exception:
            return ""

    def movie_details(self, tmdb_id, api_key):
        try:
            url = (
                "https://api.themoviedb.org/3/movie/%s?api_key=%s&language=en"
                "&append_to_response=external_ids,videos,credits,release_dates,"
                "alternative_titles,translations,images,keywords"
                "&include_image_language=en,null"
            ) % (tmdb_id, api_key)
            resp = self.get_tmdb(url)
            return self._safe_json(resp)
        except Exception:
            return None

    def tvshow_details(self, tmdb_id, api_key):
        try:
            url = (
                "https://api.themoviedb.org/3/tv/%s?api_key=%s&language=en"
                "&append_to_response=external_ids,videos,credits,content_ratings,"
                "alternative_titles,translations,images,keywords"
                "&include_image_language=en,null"
            ) % (tmdb_id, api_key)
            resp = self.get_tmdb(url)
            return self._safe_json(resp)
        except Exception:
            return None

    def season_details(self, tmdb_id, season_num, api_key, language="en"):
        try:
            url = (
                "https://api.themoviedb.org/3/tv/%s/season/%s?api_key=%s&language=%s"
                "&append_to_response=images,credits"
                "&include_image_language=en,null"
            ) % (tmdb_id, season_num, api_key, language)
            resp = self.get_tmdb(url)
            return self._safe_json(resp)
        except Exception:
            return None

    def get_movie_details(self, tmdb_id, language="en"):
        if not tmdb_id:
            return None

        tmdb_id = str(tmdb_id)
        cache_key = self._safe_cache_key(self._state_prefix(), "movie", tmdb_id)
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return cached

        response_data = self.movie_details(tmdb_id, TMDB_API_KEY)
        if not response_data:
            return None

        plot = (
            response_data.get("overview")
            or response_data.get("tagline")
            or "No plot available."
        )

        poster_path = self._pick_poster(response_data)
        fanart_path = self._pick_backdrop(response_data)

        art = self._build_art(
            poster_path=poster_path,
            fanart_path=fanart_path,
        )

        cast = response_data.get("credits", {}).get("cast", []) or []
        directors = [
            c.get("name")
            for c in response_data.get("credits", {}).get("crew", [])
            if c.get("job") == "Director" and c.get("name")
        ]
        genres = [
            g.get("name") for g in response_data.get("genres", []) if g.get("name")
        ]

        data = {
            "tmdb_id": str(response_data.get("id") or tmdb_id),
            "title": response_data.get("title"),
            "original_title": response_data.get("original_title"),
            "plot": plot,
            "year": response_data.get("release_date", "")[:4],
            "rating": response_data.get("vote_average"),
            "duration": response_data.get("runtime"),
            "premiered": response_data.get("release_date", ""),
            "art": art,
            "cast": cast,
            "director": directors,
            "genre": genres,
        }

        cache_handler.set("tmdb_data", cache_key, data)
        return data

    def get_series_details(self, tmdb_id, language="en"):
        if not tmdb_id:
            return None

        tmdb_id = str(tmdb_id)
        cache_key = self._safe_cache_key(self._state_prefix(), "series", tmdb_id)
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return cached

        response_data = self.tvshow_details(tmdb_id, TMDB_API_KEY)
        if not response_data:
            return None

        plot = (
            response_data.get("overview")
            or response_data.get("tagline")
            or "No plot available."
        )

        poster_path = self._pick_poster(response_data)
        fanart_path = self._pick_backdrop(response_data)

        art = self._build_art(
            poster_path=poster_path,
            fanart_path=fanart_path,
        )

        cast = response_data.get("credits", {}).get("cast", []) or []
        genres = [
            g.get("name") for g in response_data.get("genres", []) if g.get("name")
        ]

        data = {
            "tmdb_id": str(response_data.get("id") or tmdb_id),
            "title": response_data.get("name"),
            "original_title": response_data.get("original_name"),
            "plot": plot,
            "year": response_data.get("first_air_date", "")[:4],
            "rating": response_data.get("vote_average"),
            "premiered": response_data.get("first_air_date", ""),
            "status": response_data.get("status", ""),
            "genre": genres,
            "cast": cast,
            "art": art,
        }

        cache_handler.set("tmdb_data", cache_key, data)
        return data

    def get_season_details(self, tmdb_id, season_num, language="en"):
        if not tmdb_id:
            return None

        tmdb_id = str(tmdb_id)
        season_num = str(season_num)

        cache_key = self._safe_cache_key(
            self._state_prefix(), "season", tmdb_id, season_num
        )
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return cached

        raw = self.season_details(tmdb_id, season_num, TMDB_API_KEY, language=language)
        if not raw:
            return None

        poster_path = self._pick_poster(raw)
        fanart_path = self._pick_backdrop(raw)

        if not fanart_path:
            try:
                season_eps = raw.get("episodes") or []
                for ep in season_eps:
                    if ep.get("still_path"):
                        fanart_path = ep.get("still_path")
                        break
            except Exception:
                pass

        art = self._build_art(
            poster_path=poster_path,
            fanart_path=fanart_path,
        )

        data = {
            "tmdb_id": str(tmdb_id),
            "season": int(season_num),
            "name": raw.get("name") or f"Season {season_num}",
            "overview": raw.get("overview") or "",
            "air_date": raw.get("air_date") or "",
            "vote_average": raw.get("vote_average") or 0,
            "episode_count": len(raw.get("episodes") or []),
            "art": art,
            "raw": raw,
        }

        cache_handler.set("tmdb_data", cache_key, data)
        return data

    def get_episode_details(self, tmdb_id, season_num, episode_num, language="en"):
        if not tmdb_id:
            return None

        cache_key = self._safe_cache_key(
            self._state_prefix(), "episode", tmdb_id, season_num, episode_num
        )
        cached = cache_handler.get("tmdb_data", cache_key)
        if cached:
            return cached

        try:
            url = (
                f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}/episode/{episode_num}"
                f"?api_key={TMDB_API_KEY}&language={language}&append_to_response=images,credits"
            )
            resp = self.get_tmdb(url)
            raw = self._safe_json(resp)
            if not raw:
                return None

            still_path = raw.get("still_path")
            art = self._build_art(
                still_path=still_path,
                fanart_path=still_path,
                thumb_path=still_path,
                icon_path=still_path,
            )

            data = dict(raw)
            data["art"] = art

            cache_handler.set("tmdb_data", cache_key, data)
            return data
        except Exception:
            return None
