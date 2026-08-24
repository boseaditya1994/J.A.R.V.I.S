// Service worker (Phase 9): caches the static shell for installability,
// shows incoming Web Push notifications, and focuses the app on click.

// Bump CACHE_NAME whenever the shell files change — the activate handler
// below deletes any other cache, so a stale index.html/manifest/icon never
// keeps serving from a previous version after this file itself updates.
const CACHE_NAME = "jarvis-shell-v3";
const SHELL_FILES = ["/", "/index.html", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});

self.addEventListener("push", (event) => {
  let title = "JARVIS";
  let body = "";
  try {
    const data = event.data.json();
    title = data.title || title;
    body = data.body || "";
  } catch (err) {
    body = event.data ? event.data.text() : "";
  }
  event.waitUntil(self.registration.showNotification(title, { body, icon: "/icon.svg" }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) return client.focus();
      }
      return self.clients.openWindow("/");
    })
  );
});
