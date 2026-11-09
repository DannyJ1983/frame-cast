// Now Playing: what's on the chosen Spotify speaker, with album art, a ticking timecode and what's next.
// Runs on the 2019 TV's Chromium 63 inside the TV app, and on phones and laptops.
// Opened with ?auto=1 (by the dashboard, when music starts), it goes back to the dashboard a minute after the music stops.
(function () {
  "use strict";
  var F = window.DashboardFormat;
  var REFRESH_MS = 5000;
  var BACK_AFTER_MS = 60000;
  var $ = function (id) { return document.getElementById(id); };
  var auto = /[?&]auto=1/.test(window.location.search);
  var current = null; // the latest answer, and when it arrived
  var receivedAt = 0;
  var stoppedSince = null;
  var artUrl = "";

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function setState(state) {
    document.body.className = "state-" + state;
  }

  function showMessage(title, text, link) {
    $("message").hidden = false;
    $("message-title").textContent = title;
    var body = $("message-text");
    body.textContent = text;
    if (link) {
      body.appendChild(document.createTextNode(" "));
      body.appendChild(make("b", "", link));
    }
    setArt("");
  }

  function setArt(url) {
    if (url === artUrl) return;
    artUrl = url;
    var backdrop = $("backdrop");
    backdrop.className = "";
    if (!url) {
      $("art").removeAttribute("src");
      return;
    }
    $("art").src = url;
    backdrop.onload = function () { backdrop.className = "shown"; };
    backdrop.src = url;
  }

  /** Where the track is now: the answer's position plus the time since it arrived, while playing. */
  function position() {
    if (!current || !current.track) return 0;
    var moved = current.state === "playing" ? Date.now() - receivedAt : 0;
    return Math.min(current.track.duration_ms || 0, (current.progress_ms || 0) + moved);
  }

  function tick() {
    var now = new Date();
    $("clock").textContent = F.clockText(now);
    if (!current || !current.track) return;
    var length = current.track.duration_ms || 0;
    var at = position();
    $("elapsed").textContent = F.timecode(at);
    $("length").textContent = F.timecode(length);
    $("bar").style.width = (length ? (100 * at) / length : 0) + "%";
  }

  function renderQueue(queue) {
    var list = $("queue");
    while (list.firstChild) list.removeChild(list.firstChild);
    (queue || []).slice(0, 4).forEach(function (item) {
      var li = make("li");
      var img = make("img");
      img.alt = "";
      if (item.thumb) img.src = item.thumb;
      li.appendChild(img);
      var text = make("span", "q-text");
      text.appendChild(make("span", "q-title", item.title));
      text.appendChild(make("span", "q-artists", item.artists));
      li.appendChild(text);
      li.appendChild(make("span", "q-length", F.timecode(item.duration_ms)));
      list.appendChild(li);
    });
    $("next").hidden = !(queue && queue.length);
  }

  function render(data) {
    current = data;
    receivedAt = Date.now();
    $("note").hidden = !data.note;
    $("note").textContent = data.note || "";
    $("message").hidden = true;
    var address = window.location.protocol + "//" + window.location.host;
    if (data.state === "playing" || data.state === "paused") {
      setState(data.state);
      var track = data.track;
      $("label").textContent = (data.state === "paused" ? "Paused on " : "Now playing on ") + data.device;
      $("title").textContent = track.title;
      $("artists").textContent = track.artists;
      $("album").textContent = track.album;
      setArt(track.art);
      renderQueue(data.queue);
      tick();
    } else {
      setState(data.state);
      if (data.state === "not_set_up" || data.state === "not_connected") {
        showMessage("Spotify isn't connected", "Set it up on the phone page at", address);
      } else if (data.state === "elsewhere") {
        showMessage("Nothing playing on " + data.device, "Spotify is playing on " + data.active_device + " instead.");
      } else if (data.state === "advert") {
        showMessage("An advert is playing on " + data.device, "The music will be back in a moment.");
      } else {
        showMessage("Nothing playing on " + data.device, "Start something on Spotify and choose " + data.device + " as the speaker.");
      }
    }
    if (auto) {
      if (data.state === "playing") stoppedSince = null;
      else if (stoppedSince === null) stoppedSince = Date.now();
      else if (Date.now() - stoppedSince > BACK_AFTER_MS) window.location.replace("./");
    }
  }

  function load() {
    fetch("/api/nowplaying", { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error(response.statusText);
        return response.json();
      })
      .then(render)
      .catch(function () {
        $("note").hidden = false;
        $("note").textContent = "Can't reach the home server. Trying again…";
      });
  }

  // Inside the TV app, keys pressed while this page has focus are handed to the app.
  if (window.parent !== window) {
    document.addEventListener("keydown", function (event) {
      window.parent.postMessage({ frameCastKey: event.keyCode }, "*");
      event.preventDefault();
    });
  }

  load();
  setInterval(load, REFRESH_MS);
  setInterval(tick, 500);
  window.NowPlaying = { render: render, load: load, position: position };
})();
