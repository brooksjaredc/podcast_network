RANKING_FIELDS = {
    "pr": ("pagerank_rank", "PageRank Rankings"),
    "hub": ("hub_rank", "Hub Rankings"),
    "auth": ("authority_rank", "Authority Rankings"),
    "degree": ("degree_rank", "Degree Centrality Rankings"),
    "bt": ("betweenness_rank", "Betweenness Centrality Rankings"),
    "close": ("closeness_rank", "Closeness Centrality Rankings"),
    "appearances": ("appearances_count", "Guest Appearance Rankings"),
}

RECOMMENDATION_SORTS = {
    "rate": "Highest guest overlap",
    "overlap": "Most shared guests",
}

PODCAST_SORTS = {
    "appearances": "Most guest appearances",
    "unique": "Most unique guests",
    "latest": "Recently updated",
    "name": "Name",
}

PEOPLE_SORTS = {
    "appearances": "Most guest appearances",
    "podcasts": "Most podcasts",
    "latest": "Recently active",
    "name": "Name",
}

RANKING_DEFINITIONS = [
    {
        "name": "Guest appearances",
        "description": "Counts how many times a person appears as a guest.",
    },
    {
        "name": "PageRank",
        "description": "Highlights people connected to other important people in the network.",
    },
    {
        "name": "Hub",
        "description": "Highlights guests who point toward many prominent hosts.",
    },
    {
        "name": "Authority",
        "description": "Highlights hosts who receive links from prominent guests.",
    },
    {
        "name": "Degree",
        "description": "Counts how directly connected a person is to the rest of the network.",
    },
    {
        "name": "Betweenness",
        "description": (
            "Highlights people who sit on paths between otherwise separate parts of the network."
        ),
    },
    {
        "name": "Closeness",
        "description": (
            "Highlights people who are, on average, a short network distance from everyone else."
        ),
    },
]
