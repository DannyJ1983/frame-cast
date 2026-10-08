// Frame Cast TV app: wires the hub connection, the player, the screens and the remote.
(function () {
  "use strict";
  var core = window.FrameCastCore;
  var STORAGE_KEY = "framecast.hubUrl";
  var OSD_SECONDS = 5;
  var REPORT_EVERY_MS = 5000;
  var UNREACHABLE_AFTER_MS = 8000;

  var $ = function (id) { return document.getElementById(id); };
  var mode = "idle";
  var hub = null;
  var hubUrl = "";
  var command = null;
  var osdTimer = null;
  var lastReport = 0;
  var disconnectedSince = null;
  var keyCodes = Object.assign({}, core.KEY_CODES);

  // Storage -------------------------------------------------------------------

  function savedHubUrl() {
    try { return window.localStorage.getItem(STORAGE_KEY) || ""; } catch (e) { return ""; }
  }

  function saveHubUrl(url) {
    try { window.localStorage.setItem(STORAGE_KEY, url); } catch (e) { /* not fatal */ }
  }

  // Screens -------------------------------------------------------------------

  function setMode(next) {
    mode = next;
    document.body.className = "mode-" + next + (document.body.classList.contains("osd-visible") ? " osd-visible" : "");
  }

  function showOsd(stay) {
    document.body.classList.add("osd-visible");
    if (osdTimer) clearTimeout(osdTimer);
    osdTimer = null;
    if (!stay) {
      osdTimer = setTimeout(function () {
        if (player.state === "playing") document.body.classList.remove("osd-visible");
      }, OSD_SECONDS * 1000);
    }
  }

  function hubStatus(text, bad) {
    var el = $("hub-status");
    el.textContent = text;
    el.className = bad ? "status bad" : "status";
  }

  function updateOsd() {
    var state = player.state;
    var labels = { loading: "Loading…", buffering: "Buffering…", playing: "Playing", paused: "Paused" };
    $("osd-state").textContent = labels[state] || "";
    if (command && command.is_live) {
      $("osd-time").textContent = "Live";
      $("osd-bar").style.width = "0";
    } else {
      var position = core.formatTime(player.position);
      var duration = core.formatTime(player.duration);
      $("osd-time").textContent = duration ? position + " / " + duration : position;
      var pct = player.duration > 0 ? Math.min(100, (100 * player.position) / player.duration) : 0;
      $("osd-bar").style.width = pct + "%";
    }
  }

  // Reporting -----------------------------------------------------------------

  function report(state, message) {
    if (!hub) return;
    lastReport = Date.now();
    hub.report({
      command_id: command ? command.id : null,
      title: command ? command.title : null,
      state: state,
      message: message || null,
      position: player.position || 0,
      duration: player.duration || 0,
    });
  }

  // Player --------------------------------------------------------------------

  if (!window.webapis || !window.webapis.avplay) {
    // webapis.js comes from the TV itself; without it there is nothing to play video with.
    hubStatus("Samsung's video player isn't available on this device.", true);
    return;
  }

  var player = new window.FrameCastPlayer(window.webapis, {
    onState: function (state, detail) {
      if (state === "loading") {
        setMode("loading");
        $("loading-title").textContent = command ? command.title : "";
      } else if (state === "playing" || state === "buffering") {
        setMode("playing");
        showOsd(false);
      } else if (state === "paused") {
        setMode("playing");
        showOsd(true);
      } else if (state === "error") {
        document.body.classList.remove("osd-visible");
        $("error-message").textContent = detail;
        setMode("error");
      } else {
        document.body.classList.remove("osd-visible");
        setMode("idle");
      }
      $("osd-title").textContent = command ? command.title : "";
      updateOsd();
      report(state, detail);
    },
    onTime: function () {
      updateOsd();
      if (Date.now() - lastReport >= REPORT_EVERY_MS) report(player.state);
    },
  });

  function playCommand(next) {
    command = next;
    player.play(core.streamUrl(next, hubUrl), { userAgent: next.user_agent, isLive: next.is_live });
  }

  function handleControl(control) {
    if (control.action === "toggle") player.toggle();
    else if (control.action === "pause") player.pause();
    else if (control.action === "resume") player.resume();
    else if (control.action === "stop") player.stop();
    else if (control.action === "seek") player.seek(Number(control.seconds) || 0);
    if (mode === "playing") showOsd(player.state === "paused");
  }

  // Hub -----------------------------------------------------------------------

  function connect(url) {
    hubUrl = url;
    if (hub) hub.close();
    if (!hubUrl) {
      openSettings();
      return;
    }
    hubStatus("Connecting to " + hubUrl + "…");
    disconnectedSince = Date.now();
    hub = new window.FrameCastHubClient(hubUrl, {
      onPlay: playCommand,
      onControl: handleControl,
      onConnected: function () {
        disconnectedSince = null;
        hubStatus("Ready. Connected to " + hubUrl);
        report(player.state === "stopped" ? "idle" : player.state);
      },
      onDisconnected: function () {
        if (disconnectedSince === null) disconnectedSince = Date.now();
        hubStatus("Reconnecting to " + hubUrl + "…");
      },
    });
    hub.connect();
  }

  setInterval(function () {
    if (disconnectedSince !== null && Date.now() - disconnectedSince > UNREACHABLE_AFTER_MS) {
      hubStatus("Can't reach the home server at " + hubUrl + ". Is it running? Press OK to change the address.", true);
    }
  }, 2000);

  // Settings ------------------------------------------------------------------

  var focusables = function () { return [$("hub-input"), $("hub-save")]; };
  var focusIndex = 0;

  function focus(index) {
    var items = focusables();
    focusIndex = (index + items.length) % items.length;
    items.forEach(function (el, i) { el.classList.toggle("focused", i === focusIndex); });
    if (focusIndex !== 0) $("hub-input").blur();
  }

  function openSettings() {
    $("hub-input").value = hubUrl || "";
    setMode("settings");
    focus(0);
  }

  function saveSettings() {
    var url = core.normaliseHubUrl($("hub-input").value);
    if (!url) {
      focus(0);
      return;
    }
    saveHubUrl(url);
    setMode("idle");
    connect(url);
  }

  // Remote --------------------------------------------------------------------

  function registerKeys() {
    if (typeof tizen === "undefined" || !tizen.tvinputdevice) return;
    core.MEDIA_KEYS.forEach(function (name) {
      try {
        tizen.tvinputdevice.registerKey(name);
        keyCodes[name] = tizen.tvinputdevice.getKey(name).code;
      } catch (e) {
        console.warn("Couldn't register key " + name, e);
      }
    });
  }

  function exitApp() {
    try {
      tizen.application.getCurrentApplication().exit();
    } catch (e) {
      console.log("Exit requested (not on a TV)");
    }
  }

  document.addEventListener("keydown", function (event) {
    var name = core.keyName(event.keyCode, keyCodes);
    var action = core.keyAction(mode, name);
    if (!action) return;
    // While typing in the address box, let the keyboard handle everything but Back.
    if (mode === "settings" && document.activeElement === $("hub-input") && action !== "cancel" && action !== "move-focus") return;
    event.preventDefault();

    switch (action) {
      case "toggle": player.toggle(); showOsd(player.state === "paused"); break;
      case "resume": player.resume(); showOsd(false); break;
      case "pause": player.pause(); showOsd(true); break;
      case "seek-back": player.seek(-core.SEEK_BACK_SECONDS); showOsd(false); break;
      case "seek-forward": player.seek(core.SEEK_FORWARD_SECONDS); showOsd(false); break;
      case "show-osd": showOsd(player.state === "paused"); break;
      case "stop": player.stop(); break;
      case "dismiss": setMode("idle"); report("idle"); break;
      case "settings": openSettings(); break;
      case "exit": exitApp(); break;
      case "move-focus": focus(focusIndex + 1); break;
      case "activate":
        if (focusIndex === 0) $("hub-input").focus();
        else saveSettings();
        break;
      case "cancel":
        $("hub-input").blur();
        if (hubUrl) setMode("idle");
        else exitApp();
        break;
    }
  });

  $("hub-input").addEventListener("keydown", function (event) {
    // The TV keyboard's Done key arrives as Enter on the input.
    if (event.keyCode === 13) {
      event.stopPropagation();
      event.preventDefault();
      $("hub-input").blur();
      focus(1);
    }
  });

  document.addEventListener("visibilitychange", function () {
    player.setVisible(!document.hidden);
  });

  // Start ---------------------------------------------------------------------

  registerKeys();
  setMode("idle");
  connect(core.pickHubUrl(savedHubUrl(), (window.FRAMECAST_CONFIG || {}).hubUrl, window.location));
  window.FrameCast = { player: player, mode: function () { return mode; } };
})();
