#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
    script.module.metadatautils
    rt.py
    Get metadata from rt
"""

import os, sys
from .utils import get_json, requests, try_parse_int, log_msg
import bs4 as BeautifulSoup
from simplecache import use_cache
import json

class Rt(object):
    """Info from rt (currently only top250)"""

    def __init__(self, simplecache=None, kodidb=None):
        """Initialize - optionaly provide simplecache object"""
        if not simplecache:
            from simplecache import SimpleCache
            self.cache = SimpleCache()
        else:
            self.cache = simplecache
        if not kodidb:
            if sys.version_info.major == 3:
                from .kodidb import KodiDb
            else:
                from kodidb import KodiDb
            self.kodidb = KodiDb()
        else:
            self.kodidb = kodidb

    @use_cache(2)
    def get_details_tv_rt(self, title):
        """get rt details by providing an tvshowtitle"""
        params = {"q": title, "t": "tvseries", "limit": "1"}
        data = self.get_data(params)
        #log_msg("get_RT_all - data from json %s -%s" %  (title, data))
        return self.map_tv_details(data) if data else None

    def get_data(self, params):
        """helper method to get data from rt  API"""
        base_url = 'https://www.rottentomatoes.com/api/private/v2.0/search?'
        return get_json(base_url, params)

    def map_tv_details(self, data):
        """helper method to map the details received from rt to kodi compatible format"""
        result = {}
        if sys.version_info.major == 3:
            for key, value in data.items():
                if data and data.get("tvSeries"):
                    for item in data["tvSeries"]:
                        if item["title"]:
                            result["title"] = item["title"]
                        if item["startYear"]:
                            result["startYear"] = item["startYear"]
                        if item["endYear"]:
                            result["endYear"] = item["endYear"]
                        if item["meterClass"]:
                            result["tomatoImage"] = item["meterClass"]
                        if item["url"]:
                            result["url"] = item["url"]
                        try:
                            if item["meterScore"]:
                                result["RottenTomatoes.Meter"] = item["meterScore"]
                        except Exception:
                            pass
        return result
