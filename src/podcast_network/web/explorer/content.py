from __future__ import annotations

from typing import Any


def advanced_pages() -> dict[str, dict[str, Any]]:
    return {
        "overview": {
            "title": "Analysis Guide",
            "lede": (
                "Use this area when you want to understand the network as a system: maps, "
                "metric distributions, changes over time, categories, experimental fits, and "
                "method definitions."
            ),
            "layout": "cards",
            "sections": [
                {
                    "heading": "Network Map",
                    "body": "Start here for the visual overview of podcasts and people.",
                    "page": "map",
                    "cta": "Open map",
                },
                {
                    "heading": "Metric Distributions",
                    "body": (
                        "Inspect PageRank, hub, authority, closeness, degree, betweenness, "
                        "and leadership score distributions."
                    ),
                    "page": "metrics",
                    "cta": "View metrics",
                },
                {
                    "heading": "Network Trends",
                    "body": "See how graph size, structure, and centrality changed over time.",
                    "page": "trends",
                    "cta": "View trends",
                },
                {
                    "heading": "Categories",
                    "body": "Explore podcast categories, category mixing, and category bias.",
                    "page": "categories",
                    "cta": "View categories",
                },
                {
                    "heading": "Experimental Predictions",
                    "body": (
                        "Review network-based future link fits, score distributions, and "
                        "recent new-link checks."
                    ),
                    "page": "predictions",
                    "cta": "View fits",
                },
                {
                    "heading": "Methods",
                    "body": "Look up short definitions for the network terms used across the site.",
                    "page": "definitions",
                    "cta": "Read methods",
                },
            ],
        },
        "map": {
            "title": "Network Map",
            "lede": (
                "Two interactive views of the podcast appearance network: one centered on "
                "shows, one centered on people."
            ),
            "sections": [
                {
                    "heading": "Podcast Network Graph",
                    "body": (
                        "A full-network view of shows connected by shared guests. Use this "
                        "when you want the big picture before drilling into a path, ranking, "
                        "or recommendation."
                    ),
                    "plot": "plots/network_podcasts.html",
                },
                {
                    "heading": "People Network Graph",
                    "body": (
                        "A person-level view of hosts and guests, sized and grouped by their "
                        "position in the interview network."
                    ),
                    "plot": "plots/network_people.html",
                },
            ],
        },
        "metrics": {
            "title": "Metric Distributions",
            "lede": "Use these distributions to understand what each ranking metric is measuring.",
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
                    "plot": "plots/pr_histogram.html",
                },
                {
                    "heading": "Authority Score Histogram",
                    "body": (
                        "Authority and hub scores are computed together with the HITS "
                        "algorithm."
                    ),
                    "plot": "plots/auth_histogram.html",
                },
                {
                    "heading": "Hub Score Histogram",
                    "body": (
                        "Hub scores include all people in the network and show a broad, "
                        "long-tailed distribution."
                    ),
                    "plot": "plots/hub_histogram.html",
                },
                {
                    "heading": "Closeness Centrality Histogram",
                    "body": (
                        "Closeness centrality summarizes how near a person is to the rest "
                        "of the connected network."
                    ),
                    "plot": "plots/close_histogram.html",
                },
                {
                    "heading": "Degree Centrality Histogram",
                    "body": (
                        "Degree centrality captures how many direct podcast-network "
                        "connections a person has."
                    ),
                    "plot": "plots/degree_histogram.html",
                },
                {
                    "heading": "Betweenness Centrality Histogram",
                    "body": (
                        "Betweenness centrality highlights people who sit on many shortest "
                        "paths between others."
                    ),
                    "plot": "plots/bt_histogram.html",
                },
                {
                    "heading": "Leadership Scores",
                    "body": (
                        "Leadership scores estimate which podcasts were early to host guests "
                        "who became especially central."
                    ),
                    "plot": "plots/leader_histogram.html",
                },
            ],
        },
        "trends": {
            "title": "Network Trends",
            "lede": "Track how the podcast network grew and changed over time.",
            "sections": [
                {
                    "heading": "Evolution of the Network",
                    "body": (
                        "Release dates let us track growth over time. People and podcast "
                        "counts are shown together so their scale stays readable."
                    ),
                    "plot": "plots/evolution_global.html",
                },
                {
                    "heading": "Network Structure Evolution",
                    "body": (
                        "Path length, density, clustering, and transitivity are shown "
                        "separately from raw counts so smaller structural measures are not "
                        "flattened."
                    ),
                    "plot": "plots/evolution_structure.html",
                },
                {
                    "heading": "PageRank Evolution",
                    "body": (
                        "The top PageRank trajectories become smoother after 2015 as the "
                        "network grows and stabilizes."
                    ),
                    "plot": "plots/evolution_pr.html",
                },
                {
                    "heading": "Authority Score Evolution",
                    "body": (
                        "Authority scores show how host importance shifted as the podcast "
                        "network became denser."
                    ),
                    "plot": "plots/evolution_authority.html",
                },
                {
                    "heading": "Hub Score Evolution",
                    "body": (
                        "Hub score changes highlight highly connected guests and hosts over "
                        "time."
                    ),
                    "plot": "plots/evolution_hub.html",
                },
                {
                    "heading": "Closeness Centrality Evolution",
                    "body": (
                        "Closeness evolution shows how the network shortened or stretched "
                        "as more podcasts and people entered the data."
                    ),
                    "plot": "plots/evolution_closeness.html",
                },
            ],
        },
        "categories": {
            "title": "Categories",
            "lede": "Explore how podcast categories structure the network.",
            "sections": [
                {
                    "heading": "Podcast Categories",
                    "body": (
                        "Each podcast has one or more categories. Comedy is the dominant "
                        "first-listed category in the legacy dataset."
                    ),
                    "plot": "plots/category_podcasts.html",
                },
                {
                    "heading": "People's Top Categories",
                    "body": (
                        "People inherit a top category from the podcast where they spend the "
                        "most host or guest time."
                    ),
                    "plot": "plots/category_people.html",
                },
                {
                    "heading": "Category Mixing",
                    "body": (
                        "Category mixing describes how often links connect people from the "
                        "same or different assigned categories."
                    ),
                    "plot": "plots/category_mixing.html",
                },
                {
                    "heading": "Average Bias per Category",
                    "body": (
                        "Category bias compares a podcast's guest category mix with the "
                        "overall category distribution."
                    ),
                    "plot": "plots/category_bias.html",
                },
            ],
        },
        "definitions": {
            "title": "Methods",
            "lede": (
                "Short definitions for the network terms and derived measures used in rankings, "
                "analysis charts, and detail pages."
            ),
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
            "title": "Experimental Predictions",
            "lede": "Inspect network-based future link fits without treating them as forecasts.",
            "sections": [
                {
                    "heading": "Network-Based Future Link Fits",
                    "body": (
                        "These future link predictions are best understood as an exploratory "
                        "experiment, not a serious forecasting product. Guest booking depends on "
                        "many non-network factors: publicity cycles, availability, personal "
                        "relationships, current events, agents, geography, and randomness. The "
                        "dataset is also extremely imbalanced, and timing is especially hard: a "
                        "guest may be a plausible fit for a podcast long before they actually "
                        "appear. This feature was built mostly out of curiosity, to see how much "
                        "signal exists in the network structure itself. It can be useful for "
                        "inspecting patterns and model behavior, but the scores should not be "
                        "taken as confident predictions or recommendations."
                    ),
                },
            ],
        },
    }
