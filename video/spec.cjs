// The race film, driven by frame index from the real timings in out/jev-results.json and out/frontier-results.json.
// node ~/.claude/skills/smooth-web-video/scripts/capture.cjs video/spec.cjs video/frames
const fs = require("fs");
const path = require("path");
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "data.json"), "utf8"));

const FPS = 60;
const LEAD = 1.2; // seconds on screen before the clock starts
const RACE = 17.0; // the race clock runs in real time, Opus lands its 8th page at 16.55 s
const END = 4.3;
const FRAMES = Math.round((LEAD + RACE + END) * FPS);

const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=JetBrains+Mono:wght@500;700&family=Manrope:wght@500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#0c0c0b;color:#f4f3ee;font-family:Manrope,sans-serif}
#stage{position:absolute;inset:0;padding:34px 44px;transform-origin:50% 50%}
.top{display:flex;justify-content:space-between;align-items:baseline}
.top h1{font:400 40px/1 "Instrument Serif",serif;margin:0;letter-spacing:-.01em}
.top .sub{font:600 14px/1 Manrope;letter-spacing:.14em;text-transform:uppercase;color:#8d8c86}
#clock{font:700 34px/1 "JetBrains Mono",monospace;font-variant-numeric:tabular-nums;color:#f4f3ee}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:24px;height:548px}
.col{background:#151513;border:1px solid #2a2a27;border-radius:18px;padding:24px 26px;position:relative;overflow:hidden}
.name{display:flex;align-items:center;gap:12px;font:700 17px/1 Manrope;letter-spacing:.12em;text-transform:uppercase}
.dot{width:12px;height:12px;border-radius:50%}
.big{font:400 118px/1 "Instrument Serif",serif;margin-top:16px;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.big small{font:600 22px/1 Manrope;color:#8d8c86;letter-spacing:0;margin-left:10px}
.bar{height:6px;border-radius:3px;background:#262623;margin-top:14px;overflow:hidden}.bar i{display:block;height:100%;border-radius:3px}
.meta{display:flex;gap:30px;margin-top:16px;font:600 15px/1 Manrope;color:#8d8c86}
.meta b{display:block;margin-top:8px;font:700 24px/1 "JetBrains Mono",monospace;color:#f4f3ee;font-variant-numeric:tabular-nums}
.feed{position:absolute;left:26px;right:26px;top:318px;bottom:0;overflow:hidden;-webkit-mask-image:linear-gradient(#000 70%,transparent)}
.feed .in{position:absolute;left:0;right:0;top:0}
.row{height:34px;font:500 15.5px/34px "JetBrains Mono",monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#b9b8b1}
.row em{font-style:normal;color:#7db4ff}.row span{color:#6f6e69}
.think{position:absolute;left:26px;right:26px;top:312px;font:500 15px/27px "JetBrains Mono",monospace;color:#8d8c86}
.think div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.think .on{color:#ffb089}
.badge{position:absolute;right:24px;top:22px;font:700 13px/1 Manrope;letter-spacing:.12em;text-transform:uppercase;padding:9px 12px;border-radius:999px;background:#7db4ff;color:#0c0c0b;opacity:0}
#end{position:absolute;inset:0;background:#0c0c0b;display:flex;flex-direction:column;justify-content:center;padding:0 90px;opacity:0}
#end h2{font:400 86px/1.02 "Instrument Serif",serif;margin:0 0 26px;letter-spacing:-.015em}
#end p{font:600 27px/1.45 Manrope;color:#b9b8b1;margin:0;max-width:980px}#end p b{color:#f4f3ee}
#end .oss{margin-top:34px;font:700 17px/1 Manrope;letter-spacing:.14em;text-transform:uppercase;color:#7db4ff}
#grain{position:absolute;inset:0;width:1280px;height:720px;pointer-events:none;image-rendering:pixelated;mix-blend-mode:screen}
</style></head><body>
<div id="stage">
 <div class="top"><div><div class="sub">566 pages &middot; 8,460 link decisions &middot; same queue, same rubric, same clock</div><h1 style="margin-top:12px">Internal link audit, one whole site</h1></div><div id="clock">00.00s</div></div>
 <div class="cols">
  <div class="col"><div class="name"><span class="dot" style="background:#7db4ff"></span>Jev</div><div class="badge" id="jdone">done</div>
   <div class="big"><span id="jn">0</span><small>/ 566 pages</small></div><div class="bar"><i id="jbar" style="background:#7db4ff;width:0"></i></div>
   <div class="meta"><div>links placed<b id="jl">0</b></div><div>decisions<b id="jd">0</b></div><div>cost<b id="jc">$0.000</b></div></div>
   <div class="feed"><div class="in" id="feed"></div></div></div>
  <div class="col"><div class="name"><span class="dot" style="background:#ff8a57"></span>Claude Opus 5</div>
   <div class="big"><span id="on">0</span><small>/ 566 pages</small></div><div class="bar"><i id="obar" style="background:#ff8a57;width:0"></i></div>
   <div class="meta"><div>pages in flight<b id="of">8</b></div><div>decisions<b id="od">0</b></div><div>full pass<b>~$67</b></div></div>
   <div class="think" id="think"></div></div>
 </div>
</div>
<div id="end"><h2>566 pages in 5.9 seconds.<br>Total cost $0.27.</h2><p>Claude Opus 5 had finished <b>0 pages</b> when Jev was done, and 8 by second 16. Per page Jev is about <b>240x cheaper</b>. Every link sits on words the page already had.</p><div class="oss">open source &middot; github.com/stas4000/jev-linkmap</div></div>
<canvas id="grain" width="640" height="360"></canvas>
<script>
const D=${JSON.stringify(D)},FPS=${FPS},LEAD=${LEAD},RACE=${RACE},END=${END};
const $=id=>document.getElementById(id);
const feed=$('feed');feed.innerHTML=D.links.map(l=>'<div class="row"><em>'+l.a.replace(/</g,'&lt;')+'</em> <span>&rarr;</span> '+l.to.replace(/</g,'&lt;')+'</div>').join('');
const pages=D.fr.map(x=>x.path);
$('think').innerHTML=pages.map((p,i)=>'<div id="t'+i+'">worker '+(i+1)+'  reading '+p+'</div>').join('');
const cnt=(a,t)=>{let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(a[m]<=t)lo=m+1;else hi=m}return lo};
const lt=D.links.map(l=>l.t);let cum=0;const cc=D.jev_cost.map(([t,c])=>[t,cum+=c]);const ct=cc.map(x=>x[0]);
const ease=x=>x<0?0:x>1?1:x*x*(3-2*x);
const g=$('grain'),gx=g.getContext('2d');
function grain(i){let s=(i*2654435761)>>>0;const im=gx.createImageData(640,360),d=im.data;for(let p=0;p<d.length;p+=4){s=(s*1664525+1013904223)>>>0;const v=(s>>>24)&1?255:0;d[p]=d[p+1]=d[p+2]=v;d[p+3]=(s>>>16)%13}gx.putImageData(im,0,0)}
window.pose=i=>{const T=i/FPS,t=Math.max(0,Math.min(RACE,T-LEAD));
 $('clock').textContent=(t<10?'0':'')+t.toFixed(2)+'s';
 const jn=cnt(D.jev_at,t),jl=cnt(lt,t);$('jn').textContent=jn;$('jbar').style.width=(jn/566*100)+'%';$('jl').textContent=jl;$('jd').textContent=(jn*15-(jn>0?30:0)<0?0:Math.min(8460,Math.round(jn/566*8460))).toLocaleString('en-US');
 const k=cnt(ct,t);$('jc').textContent='$'+(k?cc[k-1][1]:0).toFixed(3);
 $('jdone').style.opacity=ease((t-D.jev_done)/0.35);
 // the feed follows the newest link while Jev runs, then keeps drifting so nothing ever holds still
 const drift=t>D.jev_done?(t-D.jev_done)*20:0;feed.style.transform='translateY('+(-(Math.max(0,jl-6)*34)+0-drift*0+ (t>D.jev_done?-0:0))+'px)';
 if(t>D.jev_done)feed.style.transform='translateY('+(-(Math.max(0,jl-6)*34)+drift)+'px)';
 const on=cnt(D.fr_at,t);$('on').textContent=on;$('obar').style.width=(on/566*100)+'%';$('od').textContent=on*15;$('of').textContent=t<=0?8:Math.max(0,8-on);
 pages.forEach((p,w)=>{const el=$('t'+w),done=D.fr[w].at<=t;el.className=done?'':'on';const dots='.'.repeat(1+Math.floor((T*3+w)%3));el.textContent='worker '+(w+1)+(done?'  done at '+D.fr[w].at.toFixed(1)+'s  '+p:'  reading '+p+' '+dots)});
 const e=ease((T-LEAD-RACE)/0.6);$('end').style.opacity=e;$('end').style.transform='scale('+(1+0.035*Math.max(0,(T-LEAD-RACE)/END))+')';
 $('stage').style.transform='scale('+(1+0.012*Math.min(1,T/(LEAD+RACE)))+')';
 grain(i)};
window.pose(0);
</script></body></html>`;

module.exports = {
  fps: FPS,
  width: 1280,
  height: 720,
  scale: 1.5,
  shots: [
    {
      html,
      ready: async (page) => page.evaluate(async () => { await document.fonts.ready; return document.fonts.check('40px "Instrument Serif"') && document.fonts.check('700 20px "JetBrains Mono"'); }),
      frames: FRAMES,
      drive: async (page, i) => page.evaluate((n) => window.pose(n), i),
    },
  ],
};
