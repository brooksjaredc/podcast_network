from pathlib import Path

from podcast_network.plots.generate import generate_all_plots, plotly_div_id


def test_generate_all_plots_creates_svg_assets() -> None:
    outputs = generate_all_plots()

    assert outputs
    assert any(path.suffix == ".svg" for path in outputs)
    assert any(path.suffix == ".html" for path in outputs)
    assert Path("static/plots/evolution_global.svg").exists()
    assert Path("static/plots/evolution_global.html").exists()
    assert Path("static/plots/evolution_structure.html").exists()
    assert "<svg" in Path("static/plots/evolution_global.svg").read_text()
    assert "Plotly.newPlot" in Path("static/plots/evolution_global.html").read_text()


def test_plotly_div_ids_are_stable() -> None:
    assert plotly_div_id("auth_histogram.html") == "podcast-network-auth-histogram"
    assert plotly_div_id("network_podcasts.html") == "podcast-network-network-podcasts"
