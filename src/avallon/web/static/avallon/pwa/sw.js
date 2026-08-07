/* Service worker: make the notes readable without a network.
 *
 * Two strategies, because the two kinds of request have opposite needs.
 *
 * The shell (stylesheet, fonts, icons) is served cache-first: going to the
 * network for it would cost a round trip per page, and it only changes when
 * avallon does. Freshness comes from the URL instead: the pages ask for
 * `style.css?v=<fingerprint>`, so an edited file is a different URL, misses
 * the cache, and is fetched. Serving it cache-first under a fixed URL is what
 * used to make a stylesheet need a hard reload to ever change again.
 *
 * The pages are network-first: notes change under the reader (another device
 * pushed, the editor saved), so a stale page is worse than a slow one. The
 * cache is the fallback, which is exactly the offline case.
 *
 * Nothing that writes is ever cached or replayed: a POST that silently
 * succeeds later, against a page that has moved on, would corrupt a note.
 */

const CACHE = 'avallon-v2';

self.addEventListener('install', (event) => {
  // Nothing is precached: the shell URLs carry a fingerprint the worker cannot
  // guess, and one visit online is enough to fill the cache with the right
  // ones. Precaching guesses would only store entries nothing ever asks for.
  event.waitUntil(self.skipWaiting());
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
        caches.open(CACHE).then((cache) => cache.keys()
          // Drop the other fingerprints of this same file, otherwise every
          // edit leaves its predecessor behind for good. Awaited before the
          // put, or a late delete would take the entry just written.
          .then((keys) => Promise.all(keys
            .filter((key) => new URL(key.url).pathname === url.pathname)
            .map((key) => cache.delete(key))))
          .then(() => cache.put(request, copy)));
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
