const CACHE_VERSION = 'v1';
const APP_CACHE = `journal-app-${CACHE_VERSION}`;
const CDN_CACHE = `journal-cdn-${CACHE_VERSION}`;

const APP_SHELL_FILES = [
    '/',
    '/styles.css',
    '/js/app.js',
    '/js/store.js',
    '/js/utils.js',
    '/js/components/Header.js',
    '/js/components/TrackerList.js',
    '/js/components/TrackerItem.js',
    '/js/components/ConfigScreen.js',
    '/js/components/ConflictResolver.js',
    '/js/components/Notifications.js',
    '/manifest.json',
    '/icons/icon-192.png',
    '/icons/icon-512.png'
];

const CDN_DEPS = [
    'https://esm.sh/preact@10.19.3',
    'https://esm.sh/preact@10.19.3/hooks',
    'https://esm.sh/@preact/signals@1.2.1?deps=preact@10.19.3',
    'https://esm.sh/htm@3.1.1',
    'https://esm.sh/localforage@1.10.0'
];

// Install: pre-cache app shell and CDN deps
self.addEventListener('install', (event) => {
    event.waitUntil(
        Promise.all([
            caches.open(APP_CACHE).then((cache) => cache.addAll(APP_SHELL_FILES)),
            caches.open(CDN_CACHE).then((cache) => cache.addAll(CDN_DEPS))
        ])
    );
    self.skipWaiting();
});

// Activate: clean up old caches and claim clients
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys
                    .filter((key) => key !== APP_CACHE && key !== CDN_CACHE)
                    .map((key) => caches.delete(key))
            );
        }).then(() => clients.claim())
    );
});

// Strip query params from URL for cache key matching
function stripQueryParams(url) {
    const u = new URL(url);
    u.search = '';
    return u.toString();
}

// Fetch: route requests to appropriate strategy
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Network-only for API requests
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // Cache-first for CDN (esm.sh) resources
    if (url.hostname === 'esm.sh') {
        event.respondWith(
            caches.open(CDN_CACHE).then((cache) => {
                return cache.match(event.request).then((cached) => {
                    if (cached) return cached;
                    return fetch(event.request).then((response) => {
                        if (response.ok) {
                            cache.put(event.request, response.clone());
                        }
                        return response;
                    });
                });
            })
        );
        return;
    }

    // Network-first for local app shell files
    event.respondWith(
        caches.open(APP_CACHE).then((cache) => {
            return fetch(event.request).then((response) => {
                if (response.ok) {
                    const cacheKey = stripQueryParams(event.request.url);
                    cache.put(new Request(cacheKey), response.clone());
                }
                return response;
            }).catch(() => {
                const cacheKey = stripQueryParams(event.request.url);
                return cache.match(cacheKey);
            });
        })
    );
});
