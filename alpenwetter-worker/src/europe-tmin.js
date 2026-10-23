import { europeTmaxPage } from "./europe-tmax.js";

// Deliberately reuse the proven cartographic editor, controls, map geometry,
// individual station styles and export. Only the data semantics and human
// labels change. IDs/styles stay unchanged within the independent Tmin page.
export function europeTminPage(){
 let html=europeTmaxPage();
 const replacements=[
  ['const PREFIX="/wolkenlabor/data/europa-tmax/";',
   'const PREFIX="/wolkenlabor/data/europa-tmin/";'],
  ['const EDIT_STORAGE="climate-europa-tmax-editor-v1";',
   'const EDIT_STORAGE="climate-europa-tmin-editor-v1";'],
  ['icon_tmax_','icon_tmin_'],
  ['tmax_c','tmin_c'],
  ['?.tx','?.tn'],
  ['station.tx','station.tn'],
  ['s.tx','s.tn'],
  ['Europa_Tmax_MOS_ICON_','Europa_Tmin_MOS_ICON_'],
  ['TMAX_2M','TMIN_2M'],
  ['MOSMIX-L TX','MOSMIX-L TN'],
  ['MOSMIX-TX','MOSMIX-TN'],
  ['TX-Werten','TN-Werten'],
  ['TX (12 h)','TN (12 h)'],
  ['06:00-18:00 UTC','18:00-06:00 UTC'],
  ['06–18 UTC','18–06 UTC'],
  ['Tageshöchsttemperaturen','Nachttiefsttemperaturen'],
  ['Tageshöchstwerte','Nachttiefstwerte'],
  ['Höchsttemperaturen','Tiefsttemperaturen'],
  ['Temperaturmaximum','Temperaturminimum'],
  ['Temperaturmaximumfelder mit Ende 06, 12 und 18 UTC',
   'Temperaturminimumfelder mit Ende 00 und 06 UTC'],
  ['MOSMIX-TN ist das 12-Stunden-Maximum gültig 18 UTC',
   'MOSMIX-TN ist das 12-Stunden-Minimum gültig 06 UTC'],
  ['Meteorologischer Zeitraum:</strong> 18–06 UTC desselben Kalendertages.',
   'Meteorologischer Zeitraum:</strong> 18 UTC am Vorabend bis 06 UTC am angezeigten Morgen.'],
  ['Fünf tägliche Prognosen, gleiche Bezugszeit 18–06 UTC.',
   'Fünf Nachtprognosen, jeweils 18–06 UTC.'],
  ['Tageskarten','Nachtkarten'],
  ['Tageskarte','Nachtkarte'],
  ['Europa Tmax','Europa Tmin'],
  ['ICON-EU-Tmax','ICON-EU-Tmin']
 ];
 for(const [before,after] of replacements){
  html=html.replaceAll(before,after);
 }
 // A night is always dated by the following 06 UTC morning.
 html=html.replace('ctx.fillText(dateLabel(day.date),1205,64);',
   'ctx.fillText("Nacht zum "+dateLabel(day.date),1110,64);');
 // Separate temperature graphics are not mutually substituted.
 return html;
}
