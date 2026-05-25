from podcast_network.paths import PROJECT_ROOT

PLOTS_DIR = PROJECT_ROOT / "static" / "plots"
WIDTH = 920
HEIGHT = 430
PALETTE = [
    "#0f766e",
    "#b45309",
    "#1d4ed8",
    "#be123c",
    "#6d28d9",
    "#15803d",
    "#c2410c",
    "#0369a1",
    "#7c2d12",
    "#4338ca",
]

APPLE_GENRE_NAMES = {
    "26": "Top Podcasts",
    "1301": "Arts",
    "1303": "Comedy",
    "1304": "Education",
    "1305": "Kids & Family",
    "1306": "Music",
    "1309": "TV & Film",
    "1310": "Music",
    "1314": "Religion & Spirituality",
    "1318": "Technology",
    "1321": "Business",
    "1324": "Society & Culture",
    "1325": "Government",
    "1326": "History",
    "1483": "Fiction",
    "1488": "True Crime",
    "1489": "News",
    "1502": "Leisure",
    "1511": "Government",
    "1512": "Health & Fitness",
    "1545": "Sports",
}

SPOTIFY_CATEGORY_NAMES = {
    "arts": "Arts",
    "business": "Business",
    "comedy": "Comedy",
    "education": "Education",
    "fiction": "Fiction",
    "health-fitness": "Health & Fitness",
    "history": "History",
    "kids-family": "Kids & Family",
    "leisure": "Leisure",
    "music": "Music",
    "news": "News",
    "religion-spirituality": "Religion & Spirituality",
    "society-culture": "Society & Culture",
    "sports": "Sports",
    "technology": "Technology",
    "true-crime": "True Crime",
    "tv-film": "TV & Film",
}

NON_CATEGORY_CHART_SOURCES = {
    "genre:26",
    "manual-target-search",
    "spotify:top-podcasts",
    "spotify:trending",
}
