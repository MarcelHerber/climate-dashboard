import unittest

from scripts.patch_sst_frontend import patch_html


FIXTURE = '''<!DOCTYPE html>
<html lang="de">
<head>
<title>Climate Dashboard Deutschland</title>
<style>body{}</style>
</head>
<body>
<div class="tabs">
  <button class="tab-button active" onclick="switchTab('monthly')">Gebietsmittel</button>
  <button class="tab-button" onclick="switchTab('era5Europe')">ERA5-Land Europa</button>
  <button class="tab-button" onclick="switchTab('records')">Stationsrekorde</button>
</div>
<div class="mobile-tab-navigation">
  <label for="mobileTabSelect">Bereich auswählen</label>
  <select id="mobileTabSelect"></select>
</div>
<div id="monthly" class="tab-content active"></div>
<div id="records" class="tab-content"></div>
<script>
Chart.register(ChartDataLabels);
</script>
</body>
</html>
'''

CURRENT_NAV_FIXTURE = '''<!DOCTYPE html>
<html lang="de">
<head>
<title>Climate Dashboard Deutschland</title>
<style>body{}</style>
</head>
<body>
<header class="dashboard-header">
  <nav class="primary-nav" aria-label="Hauptnavigation">
    <button class="nav-link tab-button active" data-nav-group="overview" onclick="switchTab('overview')">Übersicht</button>
    <div class="nav-dropdown" data-nav-group="europe">
      <button class="nav-dropdown-toggle" type="button">Europa</button>
      <div class="nav-dropdown-menu" role="menu">
        <div class="nav-menu-heading">Europa-Module</div>
        <button class="tab-button" data-nav-group="europe" onclick="switchTab('europeHub')">Europa-Überblick</button>
        <button class="tab-button" data-nav-group="europe" onclick="switchTab('europeStations')">Europa-Stationen</button>
        <button class="tab-button" data-nav-group="europe" onclick="switchTab('era5Europe')">ERA5-Land Europa</button>
      </div>
    </div>
  </nav>
</header>
<main>
  <div class="mobile-tab-navigation">
    <label for="mobileTabSelect">Bereich auswählen</label>
    <select id="mobileTabSelect"></select>
  </div>
  <div id="overview" class="tab-content active"></div>
</main>
<script>
Chart.register(ChartDataLabels);
</script>
</body>
</html>
'''


class SstFrontendPatcherTests(unittest.TestCase):
    def assert_sst_integration(self, patched):
        self.assertIn('<link rel="stylesheet" href="sst_europe.css">', patched)
        self.assertIn("switchTab('sst-europe')", patched)
        self.assertIn('id="sst-europe" class="tab-content"', patched)
        self.assertIn('<script src="sst_europe.js"></script>', patched)
        for control_id in (
            "sstRegion", "sstView", "sstDate", "sstPrevDay", "sstLatestDay",
            "sstNextDay", "sstTimeline", "sstMapImage", "sstStatus",
            "sstDataThrough", "sstPngDownload", "sstPdfDownload",
        ):
            self.assertIn(f'id="{control_id}"', patched)

    def test_adds_assets_button_and_panel_once_to_legacy_navigation(self):
        patched = patch_html(FIXTURE)
        self.assert_sst_integration(patched)

        patched_again = patch_html(patched)
        self.assertEqual(patched_again, patched)
        self.assertEqual(patched.count('href="sst_europe.css"'), 1)
        self.assertEqual(patched.count('src="sst_europe.js"'), 1)
        self.assertEqual(patched.count("switchTab('sst-europe')"), 1)

    def test_adds_sst_to_current_europe_dropdown_and_remains_idempotent(self):
        patched = patch_html(CURRENT_NAV_FIXTURE)
        self.assert_sst_integration(patched)
        self.assertIn(
            '<button class="tab-button" data-nav-group="europe" onclick="switchTab(\'sst-europe\')">Meere / SST</button>',
            patched,
        )
        self.assertLess(patched.index("switchTab('era5Europe')"), patched.index("switchTab('sst-europe')"))

        patched_again = patch_html(patched)
        self.assertEqual(patched_again, patched)
        self.assertEqual(patched.count("switchTab('sst-europe')"), 1)

    def test_missing_navigation_marker_fails_loudly(self):
        broken = FIXTURE.replace('<div class="mobile-tab-navigation">', '<div class="changed-mobile">')
        with self.assertRaisesRegex(RuntimeError, "Navigation"):
            patch_html(broken)

    def test_missing_main_script_marker_fails_loudly(self):
        broken = FIXTURE.replace('<script>\nChart.register(ChartDataLabels);', '<script>\nconsole.log("changed");')
        with self.assertRaisesRegex(RuntimeError, "Script"):
            patch_html(broken)


if __name__ == "__main__":
    unittest.main()
