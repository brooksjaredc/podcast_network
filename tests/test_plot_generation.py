from pathlib import Path

from podcast_network.plots.generate import generate_all_plots


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
