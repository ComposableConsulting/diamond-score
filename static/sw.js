/*
  Service Worker — Diamond Score
  ================================
  This file makes the app work offline (PWA).
  It caches the app shell (HTML, CSS, JS) so the UI loads even without internet.
  API calls (/api/*) are always attempted live — if they fail, the last state
  shown stays visible so scorekeeping can continue.
*/

const CACHE_NAME = 'diamond-score-v1';

const SHELL_URLS = [
  '/',
  '/history',
];

// Install: cache the app shell
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy:
//  - API calls: network first, fall through on failure (offline mode)
//  - Everything else: network first, fall back to cache
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Let API calls go straight to network — don't cache them
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request).catch(() => {
      return new Response(JSON.stringify({ error: 'offline' }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }));
    return;
  }

  // For pages: network first, cache fallback
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
