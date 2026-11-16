# HYRAS Temperatur: große Karten und interaktive Rasterabfrage

Datum: 2026-11-16

## Ziel
Tmean, Tmax und Tmin zeigen als erstes großes Hauptelement eine Deutschlandkarte der Temperaturabweichung (K) zum gewählten Klimamittel. Die bisherige Niederschlagsansicht ist der Maßstab für Größe und Bedienung. Die Gebietsmittelkurven, Rekorde, Tagesanimationen und vorhandenen Downloads bleiben erhalten und folgen darunter.

## Ansätze und Entscheidung
- Vorhandene hochauflösende PNGs direkt als Hauptkarte: sofortige Anzeige, korrekte Legende und vorhandener Download, jedoch keine exakte Zellenabfrage.
- Numerische Raster direkt im Browser darstellen: interaktive Abfrage ohne Rückschluss aus Farben, benötigt für Tmax und Tmin zusätzlich exportierte Raster.
- Gewählt: Kombination. Vorhandene PNGs dienen als große Ansicht bzw. Fallback, numerische Daten ergänzen die interaktive Darstellung. Keine geschätzten Werte aus PNG-Farben.

## Daten und Referenzen
- Bestehende HYRAS-DE-1-km-Daten nutzen. Für Tmean liegen bereits i16.gz-Raster vor. Für Tmax/Tmin beim bestehenden Kartenbau die gleichen numerischen Arrays als komprimierte int16-Raster (Skalierung 100, fehlend -32768, Nord oben) mitsamt Grid-Metadaten und Zeitraum/Referenz im Index publizieren.
- Für beide Referenzen 1991–2020 und 1961–1990 die wirkliche tagesgleiche Abweichung verwenden, auch für laufende Monate und Jahreszeiten, soweit verfügbar.
- Referenzwechsel darf niemals auf eine andere Referenz zurückfallen und falsch beschriftet werden. Fehlende Raster transparent kennzeichnen; die passende PNG-Karte bleibt sichtbar.
- Die aktuelle Monatskarte ist Standard, sofern die bisherige Auswahl nicht sinnvoll übernommen werden kann.

## Bedienung
- Desktop: Hover zeigt Rasterwert (K), optional absolute Temperatur, sofern vorhanden; Mobil: Touch. Auswahl von Zeitraum/Parameter/Referenz wirkt auf Karte und Kurven. Kartenlegende und Datum sichtbar.
- Große Karte zuerst; Kurven, Tagesanimation und Rekorde darunter; vorhandene PNG/PDF-Downloads erhalten.
- Keine Änderungen am Niederschlagsworkflow oder anderen Modulen.

## Abnahme
- Prüfen aller drei Parameter für laufenden und abgeschlossenen Monat, beide Referenzen, Datenlücken und schnelles Umschalten.
- Numerische Stichproben gegen die beim Kartenbau erzeugten Originalarrays; Rasterorientierung, Grenzen, Auflösung und Einheit überprüfen.
- Desktop- und Mobil-Layout, Karten-/Kurvendownloads sowie Rückwechsel zu Niederschlag testen.
- Erst nach bestandenen Prüfungen veröffentlichen; fehlende numerische Raster durch Datenworkflow nachziehen und den tatsächlichen Veröffentlichungsstatus transparent melden.
