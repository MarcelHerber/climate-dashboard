import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.patch_hyras_daily_anomaly_animation_frontend import patch_html


FIXTURE = '''
function hyrasDailyAnomalyPanelHtml(parameter){
  return `<div class="hyras-daily-anomaly-panel" id="hyrasDailyAnomalyPanel" data-parameter="${parameter}">
    <div class="hyras-daily-anomaly-head">
      <div>
        <h4>Tägliche 2-m-Abweichung · ${hyrasDailyAnomalyParameterLabel(parameter)}</h4>
        <p id="hyrasDailyAnomalyMeta">Tageskarte wird geladen …</p>
      </div>
    </div>
    <div class="hyras-daily-anomaly-controls">
`;
}
async function hyrasDailyAnomalyMount(parameter,rows){
  const panel=document.getElementById("hyrasDailyAnomalyPanel");
  if(!panel)return;
  const mountedPanel=panel;
  const status=panel.querySelector("#hyrasDailyAnomalyStatus");
  const image=panel.querySelector("#hyrasDailyAnomalyImage");
  try{
    const manifest=await hyrasDailyAnomalyManifest(parameter);

    // Falls während des Ladens neu gerendert wurde, darf dieser alte
    // Initialisierungslauf keine Handler an die neue Box hängen.
    if(document.getElementById("hyrasDailyAnomalyPanel")!==mountedPanel)return;

    const dates=hyrasDailyAnomalyRowsDates(rows,manifest);
  }catch(error){}
}
'''


class FrontendPatcherTests(unittest.TestCase):
    def test_adds_mp4_download_and_setup_once(self):
        patched = patch_html(FIXTURE)
        self.assertIn('id="hyrasDailyAnomalyAnimationDownload"', patched)
        self.assertIn("hyrasDailyAnomalyConfigureAnimationDownload", patched)
        self.assertIn("HYRAS_DAILY_ANIMATION_BASE", patched)
        self.assertIn('const animationParameter=animationManifest?.parameters?.[parameter]', patched)
        self.assertIn('const animation=animationParameter?.references?.[reference]', patched)
        self.assertIn('animationParameter?.data_through!==manifest?.data_through', patched)
        self.assertIn('fetch(url,{cache:"no-store"})', patched)
        self.assertIn("URL.createObjectURL", patched)
        self.assertIn("HYRAS_${label}_Tagesabweichungen_${reference}.mp4", patched)

        patched_again = patch_html(patched)
        self.assertEqual(patched_again, patched)
        self.assertEqual(patched.count('id="hyrasDailyAnomalyAnimationDownload"'), 1)

    def test_fails_loudly_when_mount_marker_is_missing(self):
        with self.assertRaisesRegex(RuntimeError, "Mount-Marker"):
            patch_html(FIXTURE.replace("async function hyrasDailyAnomalyMount", "async function changedMount"))


if __name__ == "__main__":
    unittest.main()
