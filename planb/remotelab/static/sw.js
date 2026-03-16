'use strict';

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch {}

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Skip notification if app window is currently visible
      for (const client of clientList) {
        if (client.visibilityState === 'visible') return;
      }
      return self.registration.showNotification(data.title || 'RemoteLab', {
        body: data.body || 'Task completed',
        icon: '/icon.svg',
        badge: '/apple-touch-icon.png',
        tag: 'remotelab-done',
        renotify: true,
      });
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      return self.clients.openWindow('/');
    })
  );
});
