import podcast_network.plots.generate as plot_generate
from podcast_network.plots.generate import generate_all_plots, plotly_div_id
from podcast_network.web.catalog.models import Appearance, Episode, Person, Podcast


def test_generate_all_plots_creates_svg_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plot_generate, "PLOTS_DIR", tmp_path)

    outputs = generate_all_plots()

    assert outputs
    assert any(path.suffix == ".svg" for path in outputs)
    assert any(path.suffix == ".html" for path in outputs)
    assert (tmp_path / "evolution_global.svg").exists()
    assert (tmp_path / "evolution_global.html").exists()
    assert (tmp_path / "evolution_structure.html").exists()
    assert "<svg" in (tmp_path / "evolution_global.svg").read_text()
    assert "Plotly.newPlot" in (tmp_path / "evolution_global.html").read_text()


def test_generate_all_plots_uses_database_categories(tmp_path, monkeypatch) -> None:
    podcast = Podcast.objects.create(
        name="Database Plot Podcast",
        metadata={"legacy": {"categories": ["Comedy"]}},
    )
    person = Person.objects.create(
        name="Database Plot Guest", normalized_name="database plot guest"
    )
    episode = Episode.objects.create(podcast=podcast, guid="database-plot", title="Plot episode")
    Appearance.objects.create(
        episode=episode,
        person=person,
        role=Appearance.Role.GUEST,
        source="test",
    )
    monkeypatch.setattr(plot_generate, "PLOTS_DIR", tmp_path)

    generate_all_plots()

    assert "Comedy" in (tmp_path / "category_podcasts.svg").read_text()
    assert "Comedy" in (tmp_path / "category_people.svg").read_text()


def test_plotly_div_ids_are_stable() -> None:
    assert plotly_div_id("auth_histogram.html") == "podcast-network-auth-histogram"
    assert plotly_div_id("network_podcasts.html") == "podcast-network-network-podcasts"
