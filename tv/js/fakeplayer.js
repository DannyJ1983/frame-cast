// A stand-in for Samsung's webapis.avplay, so the TV app can be tried in a desktop browser.
// It only installs itself when the real one is missing. It doesn't decode video: it shows the
// address it was asked to play and pretends time is passing. Calls are recorded in
// window.__avplayCalls for the end-to-end test. Addresses containing "fail-me" fail to load.
(function () {
  "use strict";
  if (window.webapis && window.webapis.avplay) return;

  var calls = (window.__avplayCalls = []);
  var state = "NONE";
  var url = "";
  var time = 0;
  var listener = {};
  var timer = null;

  function record(name, args) {
    calls.push([name].concat(Array.prototype.slice.call(args)));
  }

  function screen() {
    var el = document.getElementById("av-player");
    if (!el) return;
    el.style.background = state === "NONE" ? "" : "repeating-linear-gradient(45deg,#1b2a3a,#1b2a3a 40px,#22344a 40px,#22344a 80px)";
    el.setAttribute("data-fake-state", state);
    el.setAttribute("data-fake-url", url);
  }

  function stopClock() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function isLive() {
    return /live/i.test(url);
  }

  var avplay = {
    open: function (u) {
      record("open", arguments);
      url = u;
      time = 0;
      state = "IDLE";
      screen();
    },
    close: function () {
      record("close", arguments);
      stopClock();
      state = "NONE";
      url = "";
      screen();
    },
    setListener: function (l) {
      record("setListener", []);
      listener = l || {};
    },
    setDisplayRect: function () { record("setDisplayRect", arguments); },
    setDisplayMethod: function () { record("setDisplayMethod", arguments); },
    setStreamingProperty: function () { record("setStreamingProperty", arguments); },
    prepareAsync: function (success, failure) {
      record("prepareAsync", []);
      setTimeout(function () {
        if (/fail-me/.test(url)) {
          if (failure) failure({ name: "PLAYER_ERROR_CONNECTION_FAILED", message: "fake failure" });
          return;
        }
        state = "READY";
        screen();
        if (success) success();
      }, 100);
    },
    play: function () {
      record("play", arguments);
      state = "PLAYING";
      screen();
      stopClock();
      timer = setInterval(function () {
        time += 250;
        if (listener.oncurrentplaytime) listener.oncurrentplaytime(time);
      }, 250);
    },
    pause: function () {
      record("pause", arguments);
      state = "PAUSED";
      stopClock();
      screen();
    },
    stop: function () {
      record("stop", arguments);
      state = "IDLE";
      stopClock();
      screen();
    },
    seekTo: function (ms, success) {
      record("seekTo", arguments);
      time = ms;
      if (success) setTimeout(success, 0);
    },
    jumpForward: function (ms, success) {
      record("jumpForward", arguments);
      time += ms;
      if (success) setTimeout(success, 0);
    },
    jumpBackward: function (ms, success) {
      record("jumpBackward", arguments);
      time = Math.max(0, time - ms);
      if (success) setTimeout(success, 0);
    },
    getState: function () { return state; },
    getDuration: function () { return isLive() ? 0 : 600000; },
    getCurrentTime: function () { return time; },
    suspend: function () { record("suspend", arguments); },
    restore: function () { record("restore", arguments); },
  };

  window.webapis = {
    avplay: avplay,
    appcommon: {
      AppCommonScreenSaverState: { SCREEN_SAVER_OFF: 0, SCREEN_SAVER_ON: 1 },
      setScreenSaver: function () {},
    },
    productinfo: { isUdPanelSupported: function () { return false; } },
    __fake: true,
  };
})();
