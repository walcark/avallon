/* Service worker: make the notes readable without a network.
 *
 * Two strategies, because the two kinds of request have opposite needs.
 *
 * The shell (stylesheet, fonts, icons) is versioned by this file's CACHE name
 * and served cache-first: it changes when avallon is upgraded, never between
 * two reads, and going to the network for it would cost a round trip per page.
 *
 * The pages are network-first: notes change under the reader (another device
 * pushed, the editor saved), so a stale page is worse than a slow one. The
 * cache is the fallback, which is exactly the offline case.
 *
 * Nothing that writes is ever cached or replayed: a POST that silently
 * succeeds later, against a page that has moved on, would corrupt a note.
 */

const CACHE = 'avallon-v1';
const SHELL = [
  '/static/avallon/css/style.css',
  '/static/avallon/css/fonts.css',
  '/static/avallon/css/pygments.css',
  '/static/avallon/pwa/icon-192.png',
];

self.addEventListener('install', (event) => {
  // addAll rejects wholesale if one entry 404s; each is added on its own so a
  // renamed asset cannot keep the worker from installing.
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // The live-reload stream never ends: caching it would hang the worker.
  if (url.pathname.startsWith('/stream/')) return;

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
        return res;
      }))
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((res) => {
        // Only cache what a reader could usefully see again offline.
        if (res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return res;
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match('/')))
  );
});
