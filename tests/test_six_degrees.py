import unittest

from podcast_network.graph.six_degrees import (
    Edge,
    SixDegreesGraph,
    name_match_score,
    ngram_distance,
    normalize_name,
)


class SixDegreesGraphTests(unittest.TestCase):
    def test_explain_path_with_host_and_guest_edges(self) -> None:
        graph = SixDegreesGraph(
            edges=[
                Edge("Alice", "Podcast A", "host"),
                Edge("Bob", "Podcast A", "guest"),
                Edge("Bob", "Podcast B", "host"),
                Edge("Carla", "Podcast B", "guest"),
            ],
            names={"Alice", "Bob", "Carla"},
        )

        result = graph.explain("Alice", "Carla")

        self.assertTrue(result.found)
        self.assertEqual(result.length, 4)
        self.assertEqual(result.path, ("Alice", "Podcast A", "Bob", "Podcast B", "Carla"))
        self.assertIn("Alice is a host of Podcast A", result.message)
        self.assertEqual(result.message_parts[0].kind, "person")
        self.assertEqual(result.message_parts[2].kind, "podcast")

    def test_shortest_path_prefers_source_host_edges_over_guest_edges(self) -> None:
        graph = SixDegreesGraph(
            edges=[
                Edge("Alice", "Guest Podcast", "guest"),
                Edge("Guest Podcast", "Carla", "guest"),
                Edge("Alice", "Hosted Podcast", "host"),
                Edge("Hosted Podcast", "Carla", "guest"),
            ],
            names={"Alice", "Carla"},
        )

        result = graph.explain("Alice", "Carla")

        self.assertTrue(result.found)
        self.assertEqual(result.path, ("Alice", "Hosted Podcast", "Carla"))
        self.assertIn("Alice is a host of Hosted Podcast", result.message)

    def test_edge_date_is_available_for_visuals(self) -> None:
        graph = SixDegreesGraph(
            edges=[Edge("Alice", "Podcast A", "guest", date="2024-01-15")],
            names={"Alice"},
        )

        self.assertEqual(graph.edge_kind("Alice", "Podcast A"), "guest")
        self.assertEqual(graph.edge_date("Podcast A", "Alice"), "2024-01-15")

    def test_shortest_path_filters_guest_edges_by_date_window(self) -> None:
        graph = SixDegreesGraph(
            edges=[
                Edge("Alice", "Podcast A", "guest", date="2020-01-15"),
                Edge("Bob", "Podcast A", "guest", date="2024-01-15"),
                Edge("Alice", "Podcast B", "guest", date="2024-02-01"),
                Edge("Bob", "Podcast B", "guest", date="2024-02-02"),
            ],
            names={"Alice", "Bob"},
        )

        result = graph.explain("Alice", "Bob", start_date="2024-01-01", end_date="2024-12-31")

        self.assertTrue(result.found)
        self.assertEqual(result.path, ("Alice", "Podcast B", "Bob"))

    def test_shortest_path_filters_host_edges_by_active_range(self) -> None:
        graph = SixDegreesGraph(
            edges=[
                Edge(
                    "Alice",
                    "Podcast A",
                    "host",
                    active_start="2020-01-01",
                    active_end="2021-12-31",
                ),
                Edge("Bob", "Podcast A", "guest", date="2024-01-15"),
                Edge(
                    "Alice",
                    "Podcast B",
                    "host",
                    active_start="2023-01-01",
                    active_end="2025-12-31",
                ),
                Edge("Bob", "Podcast B", "guest", date="2024-02-02"),
            ],
            names={"Alice", "Bob"},
        )

        result = graph.explain("Alice", "Bob", start_date="2024-01-01", end_date="2024-12-31")

        self.assertTrue(result.found)
        self.assertEqual(result.path, ("Alice", "Podcast B", "Bob"))

    def test_explain_suggests_missing_name(self) -> None:
        graph = SixDegreesGraph(edges=[], names={"Joe Rogan", "Marc Maron"})

        result = graph.explain("Joe Rogain", "Marc Maron")

        self.assertFalse(result.found)
        self.assertEqual(result.suggestion, "Joe Rogan")
        self.assertEqual(result.suggested_source, "Joe Rogan")
        self.assertEqual(result.suggested_target, "Marc Maron")

    def test_explain_suggests_missing_target_name(self) -> None:
        graph = SixDegreesGraph(edges=[], names={"Joe Rogan", "Marc Maron"})

        result = graph.explain("Joe Rogan", "Mark Maron")

        self.assertFalse(result.found)
        self.assertEqual(result.suggestion, "Marc Maron")
        self.assertEqual(result.suggested_source, "Joe Rogan")
        self.assertEqual(result.suggested_target, "Marc Maron")

    def test_explain_resolves_normalized_name_inputs(self) -> None:
        graph = SixDegreesGraph(
            edges=[
                Edge("Joe Rogan", "The Joe Rogan Experience", "host"),
                Edge("Marc Maron", "The Joe Rogan Experience", "guest"),
            ],
            names={"Joe Rogan", "Marc Maron"},
        )

        result = graph.explain("joe rogan", "marc   maron")

        self.assertTrue(result.found)
        self.assertEqual(result.source, "Joe Rogan")
        self.assertEqual(result.target, "Marc Maron")
        self.assertEqual(result.path, ("Joe Rogan", "The Joe Rogan Experience", "Marc Maron"))

    def test_suggest_name_handles_reversed_tokens(self) -> None:
        graph = SixDegreesGraph(edges=[], names={"Joe Rogan", "Marc Maron"})

        self.assertEqual(graph.suggest_name("rogan joe"), "Joe Rogan")

    def test_normalize_name_ignores_case_accents_and_punctuation(self) -> None:
        self.assertEqual(normalize_name(" José  Andrés! "), "jose andres")

    def test_name_match_score_handles_reordered_tokens(self) -> None:
        self.assertEqual(name_match_score("rogan joe", "Joe Rogan"), 1)

    def test_ngram_distance_exact_match_is_zero(self) -> None:
        self.assertEqual(ngram_distance("marc", "marc"), 0)


if __name__ == "__main__":
    unittest.main()
