// Frame Cast TV app: wires the hub connection, the player, the channel grid, the screens and the remote.
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
        if (command && command.channel_id) focusChannel(command.channel_id);
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
    if (skipChannel && next.channel_id === skipChannel) {
      // The viewer backed out while this channel was being looked up.
      skipChannel = null;
      hub.report({ command_id: next.id, title: next.title, state: "stopped", message: null, position: 0, duration: 0 });
      return;
    }
    finding = null;
    command = next;
    $("loading-lead").textContent = "Loading";
    player.play(core.streamUrl(next, hubUrl), {
      userAgent: next.user_agent,
      isLive: next.is_live,
      adaptive: next.kind === "hls" || next.kind === "dash",
    });
  }

  function handleControl(control) {
    if (control.action === "toggle") player.toggle();
    else if (control.action === "pause") player.pause();
    else if (control.action === "resume") player.resume();
    else if (control.action === "stop") player.stop();
    else if (control.action === "seek") player.seek(Number(control.seconds) || 0);
    if (mode === "playing") showOsd(player.state === "paused");
  }

  // Channels ------------------------------------------------------------------

  var channels = [];
  var gridIndex = 0;
  var finding = null; // id of the channel being looked up, before its stream arrives
  var skipChannel = null; // a lookup the viewer backed out of

  function tileCount() {
    return channels.length + 1; // the last tile opens the server settings
  }

  function makeTile(name, logoUrl, fallback, channelId) {
    var tile = document.createElement("div");
    tile.className = "tile";
    if (channelId) tile.setAttribute("data-channel", channelId);
    var box = document.createElement("div");
    box.className = "tile-logo";
    if (logoUrl) {
      var img = document.createElement("img");
      img.alt = "";
      img.onerror = function () { box.textContent = fallback; };
      img.src = logoUrl;
      box.appendChild(img);
    } else {
      box.textContent = fallback;
    }
    var label = document.createElement("div");
    label.className = "tile-name";
    label.textContent = name;
    tile.appendChild(box);
    tile.appendChild(label);
    return tile;
  }

  function renderGrid() {
    var grid = $("grid");
    grid.textContent = "";
    $("grid-empty").style.display = channels.length ? "none" : "";
    $("hub-address").textContent = hubUrl ? " (" + hubUrl + ")" : "";
    channels.forEach(function (channel) {
      var logo = channel.has_logo && hub ? hub.logoUrl(channel) : null;
      grid.appendChild(makeTile(channel.name, logo, core.initials(channel.name), channel.id));
    });
    var settings = makeTile("Server address", null, "Settings", null);
    settings.className += " settings";
    grid.appendChild(settings);
    gridIndex = Math.min(gridIndex, tileCount() - 1);
    showFocus();
  }

  function showFocus() {
    var tiles = $("grid").children;
    for (var i = 0; i < tiles.length; i++) tiles[i].classList.toggle("focused", i === gridIndex);
    var focused = tiles[gridIndex];
    if (focused) {
      try {
        focused.scrollIntoView({ block: "nearest" });
      } catch (e) {
        focused.scrollIntoView(false);
      }
    }
  }

  function focusChannel(channelId) {
    for (var i = 0; i < channels.length; i++) {
      if (channels[i].id === channelId) gridIndex = i;
    }
    showFocus();
  }

  function playChannel(channel) {
    if (!hub) return;
    finding = channel.id;
    skipChannel = null;
    gridIndex = channels.indexOf(channel);
    document.body.classList.remove("osd-visible");
    $("loading-lead").textContent = "Finding the stream";
    $("loading-title").textContent = channel.name;
    setMode("loading");
    hub.playChannel(channel.id).then(function (result) {
      if (finding !== channel.id) return; // already playing, replaced or cancelled
      if (!result.ok) {
        finding = null;
        $("error-message").textContent = result.message;
        setMode("error");
      }
      // Otherwise the stream arrives as a play event.
    });
  }

  function cancelFinding() {
    skipChannel = finding;
    finding = null;
    setMode("idle");
    showFocus();
  }

  function stepChannel(step) {
    var next = core.neighbourChannel(channels, finding || (command && command.channel_id), step);
    if (!next) return;
    if (player.state !== "stopped") player.stop();
    playChannel(next);
  }

  function activateTile() {
    if (gridIndex < channels.length) playChannel(channels[gridIndex]);
    else openSettings();
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
      onChannels: function (list) {
        channels = list;
        renderGrid();
      },
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
      hubStatus("Can't reach the home server at " + hubUrl + ". Is it running? Choose Server address to change it.", true);
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
    core.REGISTER_KEYS.forEach(function (name) {
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
      case "stop":
        if (finding) cancelFinding();
        else player.stop();
        break;
      case "next-channel": stepChannel(1); break;
      case "prev-channel": stepChannel(-1); break;
      case "dismiss":
        setMode("idle");
        report("idle");
        showFocus();
        break;
      case "exit": exitApp(); break;
      case "move-left":
      case "move-right":
      case "move-up":
      case "move-down":
        gridIndex = core.moveFocus(gridIndex, tileCount(), core.GRID_COLUMNS, action.slice(5));
        showFocus();
        break;
      case "move-focus": focus(focusIndex + 1); break;
      case "activate":
        if (mode !== "settings") activateTile();
        else if (focusIndex === 0) $("hub-input").focus();
        else saveSettings();
        break;
      case "cancel":
        $("hub-input").blur();
        if (hubUrl) {
          setMode("idle");
          showFocus();
        } else {
          exitApp();
        }
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
  renderGrid();
  window.FrameCast = {
    player: player,
    mode: function () { return mode; },
    gridIndex: function () { return gridIndex; },
  };
})();
