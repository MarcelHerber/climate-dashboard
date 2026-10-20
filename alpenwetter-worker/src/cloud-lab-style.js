export const LAB_CSS = String.raw\`
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:#eaf2fa}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#0b1624;color:#e9f2fb}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:15px max(20px,3vw);border-bottom:1px solid #30455b;background:#101f32}
header strong{font-size:18px} header .sub{font-size:11px;color:#9ab5ca;letter-spacing:.07em;text-transform:uppercase}
a{color:#a9d5f6;text-decoration:none}a:hover{text-decoration:underline}
nav{display:flex;align-items:center;gap:12px;flex-wrap:wrap}nav form{margin:0}
button,select,input{font:inherit}button{cursor:pointer;background:#193650;color:#dbeeff;border:1px solid #43617a;border-radius:8px;padding:9px 13px}button:hover:not(:disabled){background:#285275}button:disabled{opacity:.45;cursor:not-allowed}
button.main{background:#2877a9;color:white;border-color:#3e8bb7;font-weight:750}
button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #f2b95c;outline-offset:2px}
button[aria-pressed=true]{background:#d8eaf3;color:#102b41;border-color:#d8eaf3}
.badge{font-size:11px;font-weight:800;color:#b9ebcd;background:#174436;border-radius:99px;padding:5px 9px}
main{padding:23px clamp(12px,2vw,32px) 40px;max-width:1660px;margin:auto}
h1{font-size:30px;line-height:1.1;margin:2px 0 7px}h2{font-size:16px;margin:0 0 10px}
.lead{font-size:13px;color:#9fb6cb;max-width:900px;margin:0 0 17px;line-height:1.65}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 318px;align-items:start;gap:15px}
.card{background:#122236;border:1px solid #2c445e;border-radius:12px;padding:15px;box-shadow:0 8px 30px #060d163c}
.stage{background:#08172a;border:1px solid #38536e;border-radius:9px;overflow:hidden;position:relative}
.stage canvas{width:100%;display:block;aspect-ratio:16/10}
.overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#0b213bd9;color:#c3e3fa;text-align:center;font-weight:650;padding:25px;z-index:2}
.overlay[hidden]{display:none}
.toolbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;justify-content:space-between;margin:0 0 12px}
.pill{font-size:11px;color:#b4c9da;background:#20354b;border:1px solid #3c5368;border-radius:6px;padding:5px 8px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:13px}
.controls select{background:#162e46;color:#eef6fd;border:1px solid #48627a;padding:9px;border-radius:8px}
.controls input[type=range]{flex:1;min-width:140px;accent-color:#62b9f3}
.timing{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:#b3cbdf;padding-top:10px}
.timing span{font-variant-numeric:tabular-nums}
.status{font-size:12px;color:#bad1e4;background:#1b324a;padding:10px 12px;border-radius:8px;margin-top:12px;line-height:1.5}
.status.error{color:#fbc4bb;background:#442528}
.layer{border:1px solid #365169;background:#192d43;border-radius:10px;margin-top:10px;padding:12px}
.layerTop{display:flex;align-items:center;justify-content:space-between;gap:8px}
.layerTop label{font-weight:800;font-size:13px;display:flex;gap:8px;align-items:center}
.layer .row{display:grid;grid-template-columns:102px 1fr 32px;align-items:center;gap:7px;margin-top:8px;font-size:11px;color:#c3d5e6}
.layer input[type=range]{width:100%;accent-color:#74c7ff}
.layer input[type=color]{width:34px;height:27px;border:0;background:none;padding:0}
.secondary{font-size:11px;color:#9bb1c6;line-height:1.5}
.divider{border-top:1px solid #33485f;margin:17px 0}
select{min-height:36px}
#mode{width:100%;background:#182f47;color:#e9f5fc;border:1px solid #415b73;padding:10px;border-radius:8px}
#filmCanvas{background:#24445d}
.footer{font-size:11px;color:#9cb5ca;max-width:1200px;line-height:1.6;padding-top:14px}
@media(max-width:1040px){.layout{grid-template-columns:1fr}.layerGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.layer{margin:0}}
@media(max-width:620px){.layerGrid{display:block}.layer{margin-top:10px}main{padding:14px 10px}.card{padding:10px}header{padding:12px}.controls button{padding:8px 10px}h1{font-size:24px}}
\`;