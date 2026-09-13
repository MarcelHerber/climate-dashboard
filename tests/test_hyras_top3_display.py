from pathlib import Path


def test_hyras_top3_is_below_map_and_not_drawn_into_download_canvas():
    html = Path("index.html").read_text(encoding="utf-8")
    source = Path("scripts/patch_hyras_click_timeseries_frontend.py").read_text(encoding="utf-8")

    for text in (html, source):
        assert "hyras-maxima-strip" in text
        assert "hyrasFindSeparatedMaxima(raster,state,3)" in text
        assert "hyrasMapMaxima(raster,state)" in text
        assert "wrap.appendChild(strip)" in text
        assert "hyrasDrawMapMaxima(" not in text
        assert "Die drei räumlich getrennten Maxima der aktuell dargestellten Karte stehen direkt unter der Karte." in text
