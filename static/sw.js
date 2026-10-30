// Minimal service worker: lets the phone install ClosureCheck as an app.
// It does not cache anything, because complaints must always be live.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
