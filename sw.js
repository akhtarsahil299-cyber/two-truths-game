// Minimal service worker: makes the game installable. The game needs the server, so no offline cache.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<body style="font-family:sans-serif;padding:30px;background:#2F4CFF;color:#fff"><h2>You are offline</h2><p>Connect to the internet to play.</p>',
    { headers: { 'Content-Type': 'text/html' } })));
});
