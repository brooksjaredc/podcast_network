from __future__ import annotations

from typing import Any


def advanced_pages() -> dict[str, dict[str, Any]]:
    return {
        "overview": {
            "title": "Advanced Analysis",
            "sections": [
                {
                    "heading": "Podcast Network Graph",
                    "body": (
                        "Podcasts are linked when they share guests. Link strength is based "
                        "on the number of common guests and the total time spent on each "
                        "podcast."
                    ),
                    "plotly": ("brooksjaredc:4", "o2mXOXSLBajIIoPKAcaE2q"),
                },
                {
                    "heading": "People Network Graph",
                    "body": (
                        "The people graph connects hosts and guests, with node size and "
                        "grouping driven by centrality and category structure."
                    ),
                    "plotly": ("brooksjaredc:2", "cWOUvnl7gNQJQKAaCTmUKA"),
                },
            ],
        },
        "centrality": {
            "title": "Centrality",
            "sections": [
                {
                    "heading": "Centrality Distributions",
                    "body": (
                        "Different centrality measures capture different kinds of importance, "
                        "so this page keeps them separate instead of blending scores."
                    ),
                },
                {
                    "heading": "PageRank Histogram",
                    "body": (
                        "PageRank is computed on a directed graph where guests point at "
                        "podcast hosts."
                    ),
                    "plotly": ("brooksjaredc:26", "B4JJqwu79dQQblOJFHK5UN"),
                },
                {
                    "heading": "Authority Score Histogram",
                    "body": (
                        "Authority and hub scores are computed together with the HITS "
                        "algorithm."
                    ),
                    "plotly": ("brooksjaredc:30", "rlDxLAM8J6YEscGd72dkPS"),
                },
                {
                    "heading": "Hub Score Histogram",
                    "body": (
                        "Hub scores include all people in the network and show a broad, "
                        "long-tailed distribution."
                    ),
                    "plotly": ("brooksjaredc:28", "s9UoUg6MuCVN2080ImdRD0"),
                },
                {
                    "heading": "Leadership Scores",
                    "body": (
                        "Leadership scores estimate which podcasts were early to host guests "
                        "who became especially central."
                    ),
                    "plotly": ("brooksjaredc:40", "ib8Xacn6ZaAQMx1w7yeGZ5"),
                },
            ],
        },
        "evolution": {
            "title": "Network Evolution",
            "sections": [
                {
                    "heading": "Evolution of the Network",
                    "body": (
                        "Release dates let us track growth and centrality changes over time. "
                        "The legacy analysis starts its evolution plots in 2010."
                    ),
                    "plotly": ("brooksjaredc:16", "tYkgFV9yqOdRhhjpju66za"),
                },
                {
                    "heading": "PageRank Evolution",
                    "body": (
                        "The top PageRank trajectories become smoother after 2015 as the "
                        "network grows and stabilizes."
                    ),
                    "plotly": ("brooksjaredc:18", "dLNsBE3LlzLWhIRXnWvg51"),
                },
                {
                    "heading": "Authority Score Evolution",
                    "body": (
                        "Authority scores show how host importance shifted as the podcast "
                        "network became denser."
                    ),
                    "plotly": ("brooksjaredc:22", "YljWbb8fXAGi5GXi4XdgJr"),
                },
                {
                    "heading": "Hub Score Evolution",
                    "body": (
                        "Hub score changes highlight highly connected guests and hosts over "
                        "time."
                    ),
                    "plotly": ("brooksjaredc:24", "2Mz85JMo1cstFYj2zZTpLz"),
                },
            ],
        },
        "categories": {
            "title": "Categories",
            "sections": [
                {
                    "heading": "Podcast Categories",
                    "body": (
                        "Each podcast has one or more categories. Comedy is the dominant "
                        "first-listed category in the legacy dataset."
                    ),
                    "plotly": ("brooksjaredc:10", "Ks83YPyMTXazpS8YU1MTVy"),
                },
                {
                    "heading": "People's Top Categories",
                    "body": (
                        "People inherit a top category from the podcast where they spend the "
                        "most host or guest time."
                    ),
                    "plotly": ("brooksjaredc:8", "oU9SNwUBf2Bl2KSc3aHxam"),
                },
                {
                    "heading": "Category Mixing",
                    "body": (
                        "Category mixing describes how often links connect people from the "
                        "same or different assigned categories."
                    ),
                    "plotly": ("brooksjaredc:6", "PndNEZGc3LcfNbEHWHyHbs"),
                },
                {
                    "heading": "Average Bias per Category",
                    "body": (
                        "Category bias compares a podcast's guest category mix with the "
                        "overall category distribution."
                    ),
                    "plotly": ("brooksjaredc:14", "n8Ms8VsEh95EqELCtYNRNq"),
                },
            ],
        },
        "definitions": {
            "title": "Definitions",
            "sections": [
                {
                    "heading": "PageRank",
                    "body": (
                        "Counts the number and quality of directed links to estimate node "
                        "importance."
                    ),
                },
                {
                    "heading": "Hub and Authority",
                    "body": (
                        "Mutually recursive HITS scores where authorities are pointed to by "
                        "strong hubs."
                    ),
                },
                {
                    "heading": "Degree Centrality",
                    "body": "The fraction of nodes a node is connected to.",
                },
                {
                    "heading": "Closeness Centrality",
                    "body": (
                        "A measure based on shortest path lengths from one node to the rest "
                        "of the graph."
                    ),
                },
                {
                    "heading": "Betweenness Centrality",
                    "body": (
                        "Counts how often a node lies on shortest paths between other node "
                        "pairs."
                    ),
                },
                {
                    "heading": "Unique Guests",
                    "body": (
                        "Guests who appeared on a specific podcast and no others in the "
                        "dataset."
                    ),
                },
                {
                    "heading": "Category Bias",
                    "body": (
                        "Compares a podcast's guest category mix with the overall network "
                        "category mix."
                    ),
                },
            ],
        },
        "predictions": {
            "title": "Predictions",
            "sections": [
                {
                    "heading": "Future Link Predictions",
                    "body": (
                        "The legacy project trained a model to estimate likely future podcast "
                        "and guest pairs. These tables preserve that generated output while "
                        "the model pipeline is modernized."
                    ),
                    "plotly": ("brooksjaredc:38", "uH1CwQq7XX2KUHVizaetLc"),
                },
            ],
        },
    }
