const CACHE_NAME = 'fitsync-v2-offline-gym';
const ASSETS_TO_CACHE = [
  '/',
  '/login',
  '/dashboard',
  '/today-workout',
  '/workout-plan',
  '/nutrition',
  '/exercises',
  '/form-check',
  '/progress',
  '/settings',
  '/static/css/style.css',
  '/static/manifest.json',
  '/static/js/ai_form_checker.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch(err => console.warn('[PWA] Precaching notice:', err));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      // Return cached version if found, while background-updating cache
      const fetchPromise = fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      }).catch(() => {
        // Offline fallback
        if (event.request.mode === 'navigate') {
          return caches.match('/dashboard') || caches.match('/today-workout');
        }
      });

      return cachedResponse || fetchPromise;
    })
  );
});
