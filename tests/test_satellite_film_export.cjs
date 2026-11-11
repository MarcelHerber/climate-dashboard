"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const content=fs.readFileSync("satellite_film_export.js","utf8");
const html=fs.readFileSync("satelliten.html","utf8");
const js=fs.readFileSync("satelliten.js","utf8");
function loaded(){
 const sandbox={window:{},Blob,console};
 vm.runInNewContext(content,sandbox,{timeout:2000});
 return sandbox.window.SatelliteFilmExport;
}
function parseGif(buf){
 assert.equal(Buffer.from(buf.slice(0,6)).toString(),"GIF89a");
 const width=buf[6]|(buf[7]<<8),height=buf[8]|(buf[9]<<8);
 const packed=buf[10];let at=13+((packed&0x80)?3*(1<<((packed&7)+1)):0),frames=0,delays=[],loop=false;
 const subBlocks=()=>{
  while(true){const n=buf[at++];if(n===0)break;at+=n;assert.ok(at<=buf.length);}
 };
 while(at<buf.length){
  const code=buf[at++];
  if(code===0x3b)break;
  if(code===0x21){
   const label=buf[at++];
   if(label===0xf9){
    assert.equal(buf[at++],4);
    const flags=buf[at++],delay=buf[at++]|(buf[at++]<<8);
    assert.ok((flags&4)===4,"Frames must not dispose map content");
    delays.push(delay);at+=2;
   }else{
    const n=buf[at++],header=Buffer.from(buf.slice(at,at+n)).toString("ascii");
    if(header==="NETSCAPE2.0")loop=true;
    at+=n;subBlocks();
   }
  }else if(code===0x2c){
   at+=8;
   const flags=buf[at++];
   if(flags&0x80)at+=3*(1<<((flags&7)+1));
   assert.equal(buf[at++],8,"8-bit palette LZW");
   subBlocks();frames++;
  }else throw Error("Unexpected GIF byte 0x"+code.toString(16)+" at "+(at-1));
 }
 assert.equal(buf[at-1],0x3b,"Missing GIF trailer");
 return {width,height,frames,delays,loop};
}
test("Self-contained animated GIF encoder produces valid 8-bit looping GIF89a",async()=>{
 const exp=loaded();
 const width=160,height=85,frames=Array.from({length:8},(_,step)=>
   Uint8Array.from({length:width*height},(_,i)=>(Math.floor((i%width)/7)*11+Math.floor((i/width)/5)*13+step*17)&255));
 const result=exp.indexedGIF({width,height,frames,delayCs:75});
 assert.equal(result.type,"image/gif");
 const bytes=new Uint8Array(await result.arrayBuffer());
 const parsed=parseGif(bytes);
 assert.equal(parsed.width,width);
 assert.equal(parsed.height,height);
 assert.equal(parsed.frames,8);
 assert.equal(parsed.loop,true);
 assert.deepEqual(parsed.delays,[75,75,75,75,75,75,75,75]);
 assert.ok(bytes.length>1500);
});
test("48-frame GIF remains decodable at production frame count and 320px",async()=>{
 const exp=loaded(),width=320,height=185;
 let seed=42;
 const next=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return (seed>>>16)&255;};
 const frames=Array.from({length:48},()=>Uint8Array.from({length:width*height},next));
 const result=exp.indexedGIF({width,height,frames,delayCs:42});
 const parsed=parseGif(new Uint8Array(await result.arrayBuffer()));
 assert.equal(parsed.frames,48);
 assert.equal(parsed.width,320);
 assert.equal(parsed.height,185);
 assert.equal(parsed.delays[47],42);
 assert.ok(result.size>200000);
});
test("GIF encoder refuses missing frames, invalid dimensions and mismatched buffers",()=>{
 const exp=loaded();
 assert.throws(()=>exp.indexedGIF({width:10,height:10,frames:[]}),/2 bis 48/);
 assert.throws(()=>exp.indexedGIF({width:0,height:10,frames:[new Uint8Array(100),new Uint8Array(100)]}),/Größe/);
 assert.throws(()=>exp.indexedGIF({width:10,height:10,frames:[new Uint8Array(99),new Uint8Array(100)]}),/Bildlänge/);
});
test("MP4 is not offered without actual H264 MediaRecorder; never re-label WebM",()=>{
 const exp=loaded();
 assert.equal(exp.supportsMP4(),false);
 assert.match(content,/video\/mp4;codecs=avc1\.42E01E/);
 assert.match(content,/!==\"ftyp\"/);
 assert.ok(!content.includes("video/webm"));
 assert.match(html,/id="satGif"/);
 assert.match(html,/id="satMp4"/);
 assert.match(html,/satellite_film_export\.js/);
 assert.match(js,/im\.crossOrigin="anonymous"/);
 assert.match(js,/exporters\.exportGIF/);
 assert.match(js,/exporters\.exportMP4/);
});
