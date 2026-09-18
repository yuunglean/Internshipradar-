// Service worker for Internshipradar sine push-varsler (Firebase Cloud Messaging).
// Denne filen kjøres av nettleseren i bakgrunnen, HELT UAVHENGIG av om
// index.html-fanen er åpen eller ikke — det er nettopp poenget: den lar oss vise
// et varsel om en søknadsfrist selv om ingen har siden åpen i det øyeblikket.
//
// Den bruker Firebase sine "compat"-biblioteker (ikke de moderne ES-modulene
// resten av appen bruker), fordi det er den offisielt anbefalte og mest
// pålitelige måten å sette opp en Firebase-messaging service worker på.
//
// OBS: Denne filen MÅ ligge i roten av nettstedet (samme mappe som index.html),
// ellers vil ikke nettleseren gi den riktig "scope" til å motta push-varsler for
// hele appen.

importScripts("https://www.gstatic.com/firebasejs/12.19.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.19.0/firebase-messaging-compat.js");

// Samme, ikke-hemmelige Firebase-konfigurasjon som i index.html.
firebase.initializeApp({
  apiKey: "AIzaSyD7P1FsF74gENPnJ0M_uImmwPeN2JoVJGk",
  authDomain: "internshipradar-web.firebaseapp.com",
  projectId: "internshipradar-web",
  storageBucket: "internshipradar-web.firebasestorage.app",
  messagingSenderId: "257283883876",
  appId: "1:257283883876:web:da8a520ae3e8c5d9c77071",
  measurementId: "G-ZKCQS262G1"
});

var messaging = firebase.messaging();

// Vises når et push-varsel kommer mens SIDEN IKKE er åpen i noen fane.
messaging.onBackgroundMessage(function (payload) {
  var notification = (payload && payload.notification) || {};
  var data = (payload && payload.data) || {};
  var title = notification.title || "Internshipradar";
  var options = {
    body: notification.body || "",
    icon: "icon-192.png",
    badge: "icon-120.png",
    tag: data.tag || "internshipradar-push",
    data: { url: data.url || "./" }
  };
  self.registration.showNotification(title, options);
});

// Når brukeren klikker på selve varselet: fokuser en allerede åpen fane med
// siden hvis det finnes en, ellers åpne en ny.
self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var targetUrl = (event.notification.data && event.notification.data.url) || "./";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if ("focus" in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
