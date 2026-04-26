import re
import unicodedata


SPORTS_SECTION = "sports"
SOCCER_SECTION = "soccer"
NEWS_SECTION = "news"
TV_SECTION = "tv"


LIVE_GUIDE_MEDIA_BASE = "special://home/addons/plugin.video.giptv/resources/media/liveguide"


SECTIONS = [
    {
        "key": SPORTS_SECTION,
        "label": "Sports & Live Events",
        "description": "US, Canada, and UK English sports networks, leagues, and live event channels.",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/live_sports.jpg",
    },
    {
        "key": SOCCER_SECTION,
        "label": "Soccer Leagues",
        "description": "Premier League, MLS, Champions League, Europa League, and other English soccer coverage.",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/soccer.jpg",
    },
    {
        "key": NEWS_SECTION,
        "label": "News & Local",
        "description": "US, Canada, UK, Calgary, Lethbridge, Newfoundland, and regional news.",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
    },
    {
        "key": TV_SECTION,
        "label": "TV Guide",
        "description": "Reality, lifestyle, entertainment, premium, kids, and documentary channels.",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tv_guide.jpg",
    },
]


NON_ENGLISH_OR_OUTSIDE_REGION_TERMS = [
    "deportes",
    "espanol",
    "spanish",
    "latino",
    "latam",
    "mexico",
    "mx",
    "es",
    "espana",
    "spain",
    "ar",
    "argentina",
    "brazil",
    "brasil",
    "br",
    "pt",
    "portugal",
    "portuguese",
    "fr",
    "france",
    "french",
    "de",
    "deutsch",
    "germany",
    "bundesliga",
    "it",
    "italy",
    "italia",
    "pl",
    "poland",
    "polish",
    "nl",
    "netherlands",
    "dutch",
    "se",
    "sweden",
    "swedish",
    "no",
    "norway",
    "dk",
    "danish",
    "greek",
    "greece",
    "arabic",
    "turkish",
    "india",
    "hindi",
    "punjabi",
    "pakistan",
    "my",
    "malaysia",
    "dstv",
    "osn",
    "alwan",
    "rds",
    "telemundo",
    "tudn",
    "univision",
    "af",
    "afghanistan",
]


SUPPORTED_REGION_TERMS = [
    "us",
    "usa",
    "united states",
    "america",
    "american",
    "ca",
    "canada",
    "canadian",
    "uk",
    "united kingdom",
    "britain",
    "british",
    "england",
    "english",
    "calgary",
    "lethbridge",
    "newfoundland",
    "st johns",
    "halifax",
    "toronto",
    "vancouver",
    "edmonton",
    "winnipeg",
]


REGION_PRIORITY_TERMS = [
    (0, ["ca", "canada", "canadian", "tsn", "sportsnet", "calgary", "lethbridge", "newfoundland", "st johns", "cbc", "ctv", "global", "citytv"]),
    (1, ["us", "usa", "united states", "america", "american"]),
    (2, ["uk", "gb", "united kingdom", "britain", "british", "england"]),
    (3, ["au", "australia", "australian"]),
]


REGION_BRAND_FALLBACKS = [
    (0, ["tsn", "sportsnet"]),
    (1, ["espn", "abc", "cbs", "fox", "fs1", "fs2", "nbc", "tnt", "tbs", "trutv", "tru tv", "peacock", "prime video"]),
    (2, ["sky sports", "bbc", "itv", "tnt sports uk"]),
]


ENGLISH_BRAND_TERMS = [
    "abc",
    "amc",
    "aew",
    "apple tv",
    "bbc",
    "bravo",
    "cbc",
    "cbs",
    "citytv",
    "cnn",
    "ctv",
    "cw",
    "espn",
    "espn+",
    "fox",
    "fs1",
    "fs2",
    "global",
    "hbo",
    "hgtv",
    "itv",
    "mlb",
    "nba",
    "nbc",
    "nfl",
    "nhl",
    "peacock",
    "prime video",
    "sky news",
    "sky sports",
    "sportsnet",
    "tbs",
    "tlc",
    "tnt",
    "tsn",
    "usa network",
    "wwe",
]


SPORTS_NON_CHANNEL_TERMS = [
    "news",
    "kids",
    "junior",
    "cartoon",
    "movie",
    "movies",
    "series",
    "lifestyle",
    "reality",
    "cooking",
    "food network",
    "travel",
    "weather",
    "documentary",
    "history",
]


GROUPS = [
    {
        "key": "sports_all",
        "section": SPORTS_SECTION,
        "label": "All Sports & Live Events",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/live_sports.jpg",
        "terms": [
            "sport",
            "sports",
            "live event",
            "ppv",
            "league pass",
            "nfl",
            "cfl",
            "nba",
            "nhl",
            "mlb",
            "soccer",
            "f1",
            "nascar",
            "ufc",
            "wwe",
            "aew",
        ],
        "sports_only": True,
        "priority_terms": ["nfl", "cfl", "nba", "nhl", "mlb", "f1", "nascar", "ufc", "wwe", "aew"],
    },
    {
        "key": "espn_channels",
        "section": SPORTS_SECTION,
        "label": "ESPN Channels",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/espn_channels.jpg",
        "terms": ["espn", "espn2", "espn u", "espnu", "espnews", "espn+", "sec network", "acc network"],
        "priority_terms": ["espn", "espn2", "espnu", "espnews", "espn+", "sec network", "acc network"],
    },
    {
        "key": "tnt_channels",
        "section": SPORTS_SECTION,
        "label": "TNT / TBS / truTV",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tnt_channels.jpg",
        "terms": ["tnt sports", "tnt", "tbs", "tru tv", "trutv"],
        "priority_terms": ["tbs", "tnt sports", "tnt", "trutv", "tru tv"],
    },
    {
        "key": "canadian_sports",
        "section": SPORTS_SECTION,
        "label": "TSN / Sportsnet / Canada Sports",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/canadian_sports.jpg",
        "terms": [
            "tsn",
            "tsn1",
            "tsn 1",
            "tsn2",
            "tsn 2",
            "tsn3",
            "tsn 3",
            "tsn4",
            "tsn 4",
            "tsn5",
            "tsn 5",
            "sportsnet",
            "sn360",
            "sportsnet 360",
            "sportsnet one",
            "cbc sports",
        ],
        "priority_terms": ["tsn", "sportsnet", "sn360", "cbc sports"],
    },
    {
        "key": "uk_sports",
        "section": SPORTS_SECTION,
        "label": "Sky / UK Sports",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/uk_sports.jpg",
        "terms": ["sky sports", "sky main event", "bbc sport", "itv sport", "premier sports", "tnt sports uk"],
        "priority_terms": ["sky sports", "sky main event", "tnt sports uk", "bbc sport", "itv sport"],
    },
    {
        "key": "nfl",
        "section": SPORTS_SECTION,
        "label": "NFL",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/nfl.jpg",
        "terms": [
            "nfl",
            "nfl network",
            "nfl redzone",
            "red zone",
            "redzone",
            "cbs sports",
            "cbssn",
            "fox sports",
            "fs1",
            "nbc sports",
            "espn",
            "abc",
            "prime video",
            "amazon",
            "peacock",
        ],
        "exclude_terms": ["cfl", "nba", "nhl", "mlb", "soccer"],
        "sports_only": True,
        "official_terms": ["nfl network", "nfl redzone", "red zone", "redzone", "nfl"],
        "priority_terms": ["nfl network", "nfl redzone", "redzone", "nfl", "cbs sports", "fox sports", "nbc sports", "espn", "prime video"],
    },
    {
        "key": "cfl",
        "section": SPORTS_SECTION,
        "label": "CFL",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/cfl.jpg",
        "terms": ["cfl", "cfl+", "cfl plus", "tsn", "cbs sports", "cbssn"],
        "exclude_terms": ["nfl", "nba", "nhl", "mlb", "soccer"],
        "sports_only": True,
        "official_terms": ["cfl+", "cfl plus"],
        "priority_terms": ["cfl", "cfl plus", "tsn", "cbs sports"],
    },
    {
        "key": "basketball",
        "section": SPORTS_SECTION,
        "label": "NBA / Basketball",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/basketball.jpg",
        "terms": [
            "nba",
            "nba tv",
            "nba league pass",
            "league pass",
            "wnba",
            "basketball",
            "ncaa basketball",
            "march madness",
            "espn",
            "abc",
            "nbc",
            "peacock",
            "prime video",
            "amazon prime",
            "amazon",
            "tsn",
            "sportsnet",
            "tnt sports",
            "tnt",
            "tbs",
            "tru tv",
            "trutv",
        ],
        "exclude_terms": ["nfl", "nhl", "mlb", "soccer", "football", "wwe", "aew", "ufc", "mma", "boxing"],
        "sports_only": True,
        "official_terms": [
            "nba league pass",
            "league pass",
            "nba tv",
            "nba",
            "wnba",
            "celtics",
            "lakers",
            "warriors",
            "raptors",
            "knicks",
            "bulls",
            "heat",
            "mavericks",
            "suns",
            "spurs",
            "nuggets",
            "bucks",
            "cavaliers",
            "76ers",
            "sixers",
        ],
        "priority_terms": [
            "nba league pass",
            "league pass",
            "nba tv",
            "nba",
            "prime video nba",
            "wnba",
            "basketball",
            "espn",
            "abc",
            "nbc",
            "tnt",
            "tbs",
            "trutv",
            "tsn",
            "sportsnet",
        ],
    },
    {
        "key": "hockey",
        "section": SPORTS_SECTION,
        "label": "NHL / Hockey",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/hockey.jpg",
        "terms": [
            "nhl",
            "nhl network",
            "hockey",
            "ahl",
            "chl",
            "world juniors",
            "sportsnet",
            "cbc",
            "hockey night",
            "tsn",
            "espn",
            "abc",
            "tnt sports",
            "tnt",
            "tbs",
            "tru tv",
            "trutv",
        ],
        "exclude_terms": ["nba", "nfl", "mlb", "soccer"],
        "sports_only": True,
        "official_terms": [
            "nhl center ice",
            "nhl network",
            "nhl",
            "hockey night",
            "ahl",
            "maple leafs",
            "leafs",
            "canadiens",
            "habs",
            "oilers",
            "flames",
            "canucks",
            "jets",
            "senators",
            "bruins",
            "rangers",
            "penguins",
            "blackhawks",
            "red wings",
            "avalanche",
            "golden knights",
        ],
        "priority_terms": [
            "nhl center ice",
            "nhl network",
            "nhl",
            "hockey night",
            "sportsnet",
            "cbc",
            "tsn",
            "espn",
            "tnt",
            "tbs",
            "trutv",
            "ahl",
            "chl",
            "hockey",
        ],
    },
    {
        "key": "baseball",
        "section": SPORTS_SECTION,
        "label": "MLB / Baseball",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/baseball.jpg",
        "terms": ["mlb", "mlb network", "baseball", "espn", "fox sports", "fs1", "tbs", "apple tv", "sportsnet", "tsn"],
        "exclude_terms": ["nba", "nfl", "nhl", "soccer"],
        "sports_only": True,
        "official_terms": ["mlb network", "mlb", "baseball"],
        "priority_terms": ["mlb", "mlb network", "baseball", "fox sports", "espn", "tbs", "apple tv"],
    },
    {
        "key": "formula_one",
        "section": SPORTS_SECTION,
        "label": "Formula 1 / F1",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/formula_one.jpg",
        "terms": ["formula 1", "formula one", "f1", "f1 tv", "sky sports f1", "espn f1", "tsn f1"],
        "priority_before_region": True,
        "priority_terms": ["sky sports f1", "f1 tv", "formula 1", "formula one", "f1", "espn f1", "tsn f1"],
    },
    {
        "key": "nascar",
        "section": SPORTS_SECTION,
        "label": "NASCAR",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/nascar.jpg",
        "terms": ["nascar", "cup series", "xfinity series", "fox sports", "fs1", "nbc sports", "usa network"],
        "exclude_terms": ["kids", "movie", "news"],
        "sports_only": True,
        "official_terms": ["nascar", "cup series", "xfinity series"],
        "priority_terms": ["nascar", "cup series", "xfinity", "fox sports", "nbc sports", "usa network"],
    },
    {
        "key": "soccer_all",
        "section": SOCCER_SECTION,
        "label": "Soccer",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/soccer.jpg",
        "terms": ["soccer", "football", "premier league", "epl", "mls", "champions league", "europa league", "fa cup", "efl", "nwsl", "world cup"],
        "exclude_terms": ["nfl", "cfl", "nba", "nhl", "mlb"],
        "sports_only": True,
        "priority_before_region": True,
        "priority_terms": ["premier league", "epl", "mls", "champions league", "europa league", "fa cup", "efl", "nwsl", "soccer", "football"],
    },
    {
        "key": "soccer_premier_league",
        "section": SOCCER_SECTION,
        "label": "Premier League / EPL",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/soccer.jpg",
        "terms": ["premier league", "epl", "nbc sports", "usa network", "peacock", "sky sports premier league", "sky sports football", "tnt sports"],
        "exclude_terms": ["nfl", "cfl", "nba", "nhl", "mlb"],
        "sports_only": True,
        "priority_before_region": True,
        "priority_terms": ["premier league", "epl", "sky sports premier league", "nbc sports", "usa network", "peacock"],
    },
    {
        "key": "soccer_mls",
        "section": SOCCER_SECTION,
        "label": "MLS",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/soccer.jpg",
        "terms": ["mls", "major league soccer", "apple tv", "apple", "fox sports", "fs1", "tsn"],
        "exclude_terms": ["nfl", "cfl", "nba", "nhl", "mlb"],
        "sports_only": True,
        "priority_before_region": True,
        "priority_terms": ["mls", "major league soccer", "apple tv", "fox sports", "tsn"],
    },
    {
        "key": "soccer_champions_league",
        "section": SOCCER_SECTION,
        "label": "Champions / Europa",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/soccer.jpg",
        "terms": ["champions league", "europa league", "paramount", "cbs sports", "tnt sports", "dazn"],
        "exclude_terms": ["nfl", "cfl", "nba", "nhl", "mlb"],
        "sports_only": True,
        "priority_before_region": True,
        "priority_terms": ["champions league", "europa league", "paramount", "cbs sports", "tnt sports", "dazn"],
    },
    {
        "key": "mma_boxing",
        "section": SPORTS_SECTION,
        "label": "MMA / Boxing / UFC",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/mma_boxing.jpg",
        "terms": ["ufc", "mma", "boxing", "fight", "fights", "espn+", "dazn", "sky sports box office", "box office"],
        "sports_only": True,
        "priority_terms": ["ufc", "mma", "boxing", "fight", "espn+", "dazn"],
    },
    {
        "key": "wrestling",
        "section": SPORTS_SECTION,
        "label": "WWE / AEW",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/wrestling.jpg",
        "terms": ["wwe", "aew", "wwe raw", "smackdown", "nxt"],
        "official_terms": ["wwe network", "aew plus", "wwe", "aew"],
        "priority_terms": ["wwe network", "aew plus", "wwe", "aew"],
    },
    {
        "key": "golf_tennis",
        "section": SPORTS_SECTION,
        "label": "Golf / Tennis",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/golf_tennis.jpg",
        "terms": ["golf", "golf channel", "pga", "liv golf", "tennis", "tennis channel"],
        "priority_terms": ["golf", "tennis", "pga", "liv golf"],
    },
    {
        "key": "calgary_news",
        "section": NEWS_SECTION,
        "label": "Calgary News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["calgary", "cbc calgary", "ctv calgary", "global calgary", "citynews calgary"],
        "priority_terms": ["cbc calgary", "ctv calgary", "global calgary", "citynews calgary", "calgary"],
    },
    {
        "key": "lethbridge_news",
        "section": NEWS_SECTION,
        "label": "Lethbridge News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["lethbridge", "global lethbridge", "ctv lethbridge", "bridge city news"],
        "priority_terms": ["global lethbridge", "ctv lethbridge", "bridge city news", "lethbridge"],
    },
    {
        "key": "newfoundland_news",
        "section": NEWS_SECTION,
        "label": "Newfoundland News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["newfoundland", "st johns", "st. johns", "ntv", "cbc newfoundland", "cbc nl"],
        "priority_terms": ["ntv", "cbc newfoundland", "cbc nl", "st johns", "newfoundland"],
    },
    {
        "key": "canada_local_news",
        "section": NEWS_SECTION,
        "label": "Canada News - Calgary / Lethbridge / Newfoundland",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": [
            "calgary",
            "lethbridge",
            "newfoundland",
            "st johns",
            "st. johns",
            "cbc calgary",
            "ctv calgary",
            "global calgary",
            "global lethbridge",
            "ntv",
            "cbc news",
            "ctv news",
            "global news",
            "citynews",
            "cp24",
            "bnn",
        ],
        "priority_terms": ["calgary", "lethbridge", "newfoundland", "cbc", "ctv", "global"],
    },
    {
        "key": "canada_news",
        "section": NEWS_SECTION,
        "label": "Canada News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": [
            "cbc news",
            "ctv news",
            "global news",
            "citynews",
            "cp24",
            "bnn",
            "canada news",
            "calgary",
            "edmonton",
            "lethbridge",
            "newfoundland",
            "halifax",
            "toronto",
            "vancouver",
            "winnipeg",
        ],
        "priority_terms": ["cbc news", "ctv news", "global news", "citynews", "cp24", "bnn"],
    },
    {
        "key": "us_news",
        "section": NEWS_SECTION,
        "label": "USA News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["cnn", "fox news", "msnbc", "abc news", "cbs news", "nbc news", "newsmax", "usa news", "us news"],
        "priority_terms": ["cnn", "fox news", "msnbc", "abc news", "cbs news", "nbc news", "newsmax"],
    },
    {
        "key": "uk_news",
        "section": NEWS_SECTION,
        "label": "UK News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["bbc news", "sky news", "gb news", "itv news", "uk news"],
        "priority_terms": ["bbc news", "sky news", "gb news", "itv news"],
    },
    {
        "key": "us_uk_news",
        "section": NEWS_SECTION,
        "label": "US / UK News",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/news.jpg",
        "terms": ["cnn", "fox news", "msnbc", "abc news", "cbs news", "nbc news", "newsmax", "bbc news", "sky news", "gb news", "itv news"],
        "priority_terms": ["bbc news", "sky news", "cnn", "fox news", "msnbc", "abc news", "cbs news", "nbc news"],
    },
    {
        "key": "reality_lifestyle",
        "section": TV_SECTION,
        "label": "Reality / Lifestyle",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/reality_tv.jpg",
        "terms": [
            "bravo",
            "tlc",
            "hgtv",
            "food network",
            "magnolia",
            "e entertainment",
            "mtv",
            "vh1",
            "we tv",
            "own",
            "lifetime",
            "a&e",
            "id",
            "investigation discovery",
            "discovery",
            "travel channel",
            "slice",
            "w network",
            "home network",
            "makeful",
        ],
    },
    {
        "key": "entertainment",
        "section": TV_SECTION,
        "label": "Entertainment",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tv_guide.jpg",
        "terms": ["abc", "cbs", "nbc", "fox", "cw", "ctv", "global", "citytv", "showcase", "usa network", "tbs", "tnt", "fx", "fxx", "amc", "syfy", "comedy central", "paramount network"],
        "exclude_terms": ["news", "sports", "sport"],
    },
    {
        "key": "movies_premium",
        "section": TV_SECTION,
        "label": "Movies / Premium",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tv_guide.jpg",
        "terms": ["hbo", "showtime", "starz", "cinemax", "tmn", "crave", "movie network", "epix", "mgm+", "flix", "movie", "movies"],
    },
    {
        "key": "kids_family",
        "section": TV_SECTION,
        "label": "Kids / Family",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tv_guide.jpg",
        "terms": ["disney", "disney channel", "disney junior", "nick", "nickelodeon", "cartoon network", "boomerang", "treehouse", "pbs kids", "family channel", "teletoon", "ytv"],
    },
    {
        "key": "documentary_knowledge",
        "section": TV_SECTION,
        "label": "Documentary / Knowledge",
        "art": f"{LIVE_GUIDE_MEDIA_BASE}/tv_guide.jpg",
        "terms": ["discovery", "history", "nat geo", "national geographic", "smithsonian", "science channel", "animal planet", "bbc earth", "documentary", "knowledge"],
    },
]


GROUP_LOOKUP = {group["key"]: group for group in GROUPS}


KODI_MARKUP_RE = re.compile(r"\[(?:/?B|/?I|/?COLOR(?:\s+[^\]]+)?)\]", re.IGNORECASE)
GENERIC_BRACKET_RE = re.compile(r"\[[^\]]+\]")
BRACKET_REGION_RE = re.compile(
    r"^\s*[\[(]\s*(?:usa|canada|england|australia|us|ca|uk|gb|eng|au)\s*[\])]\s*[:|\-/]*\s*",
    re.IGNORECASE,
)
REGION_DELIMITER_RE = re.compile(
    r"^\s*(?:usa|canada|england|australia|us|ca|uk|gb|eng|au)\s*[:|\-/]+\s*",
    re.IGNORECASE,
)
REGION_CODE_PREFIX_RE = re.compile(r"^\s*(?:us|ca|uk|gb|eng|au)\s+", re.IGNORECASE)
QUALITY_TOKEN_RE = re.compile(
    r"\b(?:live|fhd|hd|sd|uhd|4k|8k|1080p|720p|2160p|h\.?264|h\.?265|hevc|x264|x265)\b",
    re.IGNORECASE,
)


def normalize_text(value):
    value = value or ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower()
    value = re.sub(r"[^a-z0-9+]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_display_name(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = KODI_MARKUP_RE.sub("", value)
    value = re.sub(r"[\[(]\s*live\s*[\])]\s*", " ", value, flags=re.IGNORECASE)
    value = BRACKET_REGION_RE.sub("", value)
    value = REGION_DELIMITER_RE.sub("", value)
    value = REGION_CODE_PREFIX_RE.sub("", value)
    value = GENERIC_BRACKET_RE.sub(" ", value)
    value = re.sub(r"\s+[\[(]\s*(?:us|usa|ca|canada|uk|gb|eng|england)\s*[\])]\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*[:|]\s*", " ", value)
    value = re.sub(r"\s+-\s+", " ", value)
    value = QUALITY_TOKEN_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" -_|")
    return value or "Unknown Channel"


def clean_description(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = KODI_MARKUP_RE.sub("", value)
    value = BRACKET_REGION_RE.sub("", value)
    value = REGION_DELIMITER_RE.sub("", value)
    value = REGION_CODE_PREFIX_RE.sub("", value)
    value = GENERIC_BRACKET_RE.sub(" ", value)
    value = QUALITY_TOKEN_RE.sub("", value)
    value = re.sub(r"\s*[:|]\s*", " ", value)
    value = re.sub(r"\s+-\s+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_|")
    return value


def _term_matches(text, term):
    term = normalize_text(term)
    if not term:
        return False
    padded_text = f" {text} "
    padded_term = f" {term} "
    return padded_term in padded_text


def stream_search_text(stream):
    fields = [
        stream.get("name"),
        stream.get("title"),
        stream.get("stream_display_name"),
        stream.get("category_name"),
        stream.get("epg_channel_id"),
    ]
    return normalize_text(" ".join(str(field or "") for field in fields))


def sections():
    return list(SECTIONS)


def groups_for_section(section_key):
    return [group for group in GROUPS if group["section"] == section_key]


def get_group(group_key):
    return GROUP_LOOKUP.get(group_key)


def art_for_group(group_key):
    group = get_group(group_key)
    if group:
        return group.get("art", "")
    return ""


def is_supported_region_stream(stream):
    text = stream_search_text(stream)
    if not text:
        return False
    if any(_term_matches(text, term) for term in NON_ENGLISH_OR_OUTSIDE_REGION_TERMS):
        return False
    return any(_term_matches(text, term) for term in SUPPORTED_REGION_TERMS + ENGLISH_BRAND_TERMS)


def group_matches_stream(group, stream):
    text = stream_search_text(stream)
    if not text or not is_supported_region_stream(stream):
        return False

    for term in group.get("exclude_terms", []):
        if _term_matches(text, term):
            return False

    if group.get("sports_only"):
        for term in SPORTS_NON_CHANNEL_TERMS:
            if _term_matches(text, term):
                return False

    return any(_term_matches(text, term) for term in group.get("terms", []))


def _dedupe_key(stream):
    stream_id = stream.get("stream_id") or stream.get("id")
    if stream_id not in (None, ""):
        return ("id", str(stream_id))
    return ("name", normalize_text(stream.get("name") or stream.get("title") or ""))


def _priority_rank(group, stream):
    text = stream_search_text(stream)
    for index, term in enumerate(group.get("priority_terms", [])):
        if _term_matches(text, term):
            return index
    return len(group.get("priority_terms", [])) + 1


def _official_rank(group, stream):
    text = stream_search_text(stream)
    display = normalize_text(_display_name(stream))
    official_terms = group.get("official_terms", [])
    best = None

    for index, term in enumerate(official_terms):
        normalized_term = normalize_text(term)
        if not normalized_term or not _term_matches(text, term):
            continue

        if display == normalized_term or display.startswith(f"{normalized_term} "):
            match_shape = 0
        elif _term_matches(display, term):
            match_shape = 1
        else:
            match_shape = 2

        candidate = (match_shape, index)
        if best is None or candidate < best:
            best = candidate

    if best is not None:
        return best

    return (3, len(official_terms) + 1)


def _region_rank(stream):
    text = stream_search_text(stream)
    for rank, terms in REGION_PRIORITY_TERMS:
        if any(_term_matches(text, term) for term in terms):
            return rank
    for rank, terms in REGION_BRAND_FALLBACKS:
        if any(_term_matches(text, term) for term in terms):
            return rank
    return 4


def _display_name(stream):
    return clean_display_name(
        stream.get("name") or stream.get("title") or stream.get("stream_display_name") or ""
    )


def match_streams(streams, group_key):
    group = get_group(group_key)
    if not group:
        return []

    matched = []
    seen = set()
    for stream in streams or []:
        if not isinstance(stream, dict):
            continue
        if not group_matches_stream(group, stream):
            continue
        key = _dedupe_key(stream)
        if key in seen:
            continue
        seen.add(key)
        matched.append(stream)

    def sort_key(item):
        display = normalize_text(_display_name(item))
        official_shape, official_rank = _official_rank(group, item)
        if official_shape < 3:
            return (0, official_shape, official_rank, _region_rank(item), display)

        priority_rank = _priority_rank(group, item)
        region_rank = _region_rank(item)
        if group.get("section") not in (SPORTS_SECTION, SOCCER_SECTION, NEWS_SECTION):
            return (1, priority_rank, 0, display)
        if group.get("region_before_priority"):
            return (1, region_rank, priority_rank, display)
        return (1, priority_rank, region_rank, display)

    return sorted(matched, key=sort_key)
