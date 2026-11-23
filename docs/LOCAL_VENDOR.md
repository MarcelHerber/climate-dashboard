# Lokale Bibliotheken – Performance Schritt 5

Die Hauptseite lädt die untenstehenden, **unveränderten Originaldateien** aus `vendor/`. Sie wurden am 23.11.2026 über GitHub Actions aus den angegebenen, fest versionierten CDN-URLs heruntergeladen und per vollständigem SHA-256 geprüft. Die erwarteten SHA-256-Werte und alle 13 Dateien stehen in `tools/import_vendor_assets.py`.

| Komponente | Version | Originalquelle |
|---|---|---|
| Chart.js | 4.4.1 | https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js |
| chartjs-plugin-zoom | 2.0.1 | https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js |
| chartjs-chart-matrix | 1.3.0 | https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@1.3.0/dist/chartjs-chart-matrix.min.js |
| chartjs-plugin-datalabels | 2.2.0 | https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0 |
| jsPDF | 4.2.1 | https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js |
| html2canvas | 1.4.1 | https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js |
| Leaflet | 1.9.4 | https://unpkg.com/leaflet@1.9.4/dist/leaflet.js und leaflet.css |

Zusätzlich liegen in `vendor/leaflet/1.9.4/dist/images/` die fünf Originalgrafiken für Standardmarker, Schatten und Ebenen-Schalter. Die lokalen `leaflet.css`-URLs bleiben relativ zum CSS-Dateipfad. Im Pages-Build wird **der gesamte Vendor-Ordner** kopiert und mittels `--static-dir vendor` verifiziert.

Die Ladeattribute der Hauptseite bleiben unverändert: Chart.js/Plugins synchron; jsPDF und html2canvas mit `defer`; Leaflet mit `async` und `dashboardLeafletScript`. Notfall-Ladeversuche in MOSMIX und in den Europa-Stationen verwenden ebenfalls lokale Vendor-Pfade. Die referenzierten `?v=`-Hashes werden nach dem vollständigen Staging automatisch aus dem Dateiinhalt generiert.

## Scope

Weitere Bibliotheken, die eigene Unterseiten nachladen (z. B. D3 oder svg2pdf.js), und Datenquellen `cdn.jsdelivr.net/gh/` bleiben in Schritt 5 unverändert. Vor einem kompletten CDN-unabhängigen Betrieb müssen diese separat inventarisiert und lokal bereitgestellt werden.

## Rechtehinweise

Die jeweiligen Urheberrechts- und Lizenzhinweise der verwendeten Pakete sind bei einer Weiterverteilung zu beachten. Maßgeblich sind die Originalpakete und deren Lizenzdateien (etwa `https://www.npmjs.com/package/chart.js/v/4.4.1`, `https://www.npmjs.com/package/leaflet/v/1.9.4`). Neue Upstream-Versionen dürfen nicht stillschweigend übernommen werden; sie erfordern erneut vollständigen Hash-Abgleich, Chart/Map/Exporttests und eine gezielte Freigabe.
