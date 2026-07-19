const CACHE='life-shell-v1';
const ASSETS=['./','./index.html','./config.js','./manifest.webmanifest','./icon-192.png','./icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
 // アプリの殻(HTML/JS/アイコン)だけをキャッシュする。GAS Web Appとの通信
 // (state取得・書き込み)はページ側がCache Storage+未送信キューで面倒を見る。
 e.respondWith(
  fetch(e.request).then(r=>{
   if(e.request.method==='GET'&&r.ok&&new URL(e.request.url).origin===location.origin){
    const cp=r.clone();caches.open(CACHE).then(c=>c.put(e.request,cp));}
   return r;
  }).catch(()=>caches.match(e.request,{ignoreSearch:true}).then(m=>m||caches.match('./index.html')))
 );
});
