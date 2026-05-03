import unittest

from podcast_network.graph.six_degrees import Edge, SixDegreesGraph, ngram_distance


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

    def test_explain_suggests_missing_name(self) -> None:
        graph = SixDegreesGraph(edges=[], names={"Joe Rogan", "Marc Maron"})

        result = graph.explain("Joe Rogain", "Marc Maron")

        self.assertFalse(result.found)
        self.assertEqual(result.suggestion, "Joe Rogan")

    def test_ngram_distance_exact_match_is_zero(self) -> None:
        self.assertEqual(ngram_distance("marc", "marc"), 0)


if __name__ == "__main__":
    unittest.main()
