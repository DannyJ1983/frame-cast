// Pure helpers for the TV app: no DOM, no Samsung APIs, so Node can test them.
// Written for the 2019 TV's Chromium 63: no optional chaining, no ?? and no ES modules.
(function (root, factory) {
  var core = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = core;
  else root.FrameCastCore = core;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DEFAULT_PORT = 8090;

  // Key codes the Samsung remote sends. Media keys only arrive once registered.
  var KEY_CODES = {
    Enter: 13,
    Left: 37,
    Up: 38,
    Right: 39,
    Down: 40,
    Return: 10009,
    MediaPlayPause: 10252,
    MediaPlay: 415,
    MediaPause: 19,
    MediaStop: 413,
    MediaFastForward: 417,
    MediaRewind: 412,
  };
  var MEDIA_KEYS = ["MediaPlayPause", "MediaPlay", "MediaPause", "MediaStop", "MediaFastForward", "MediaRewind"];
  // Desktop keyboard equivalents, for trying the app in a browser.
  var BROWSER_KEYS = { 27: "Return", 8: "Return", 32: "MediaPlayPause" };

  var SEEK_BACK_SECONDS = 10;
  var SEEK_FORWARD_SECONDS = 30;

  /** Turn "192.168.1.20" or "192.168.1.20:8090/" into "http://192.168.1.20:8090". */
  function normaliseHubUrl(text) {
    var value = String(text || "").trim();
    if (!value) return "";
    if (!/^https?:\/\//i.test(value)) value = "http://" + value;
    var match = /^(https?:\/\/)([^\/?#]+)/i.exec(value);
    if (!match) return "";
    var host = match[2];
    if (!/:\d+$/.test(host) && !/^\[.*\]$/.test(host)) host += ":" + DEFAULT_PORT;
    return match[1].toLowerCase() + host;
  }

  /**
   * Pick the hub address: one saved on the TV wins, then the one built into the app,
   * then (in a browser) the hub the page was loaded from.
   */
  function pickHubUrl(saved, configured, location) {
    if (saved) return normaliseHubUrl(saved);
    if (configured) return normaliseHubUrl(configured);
    if (location && /^https?:$/.test(location.protocol)) return location.protocol + "//" + location.host;
    return "";
  }

  /** Relay commands carry a path on the hub ("/p/..."); everything else is already absolute. */
  function streamUrl(command, hubUrl) {
    var url = command && command.url ? String(command.url) : "";
    if (url.charAt(0) === "/") return hubUrl.replace(/\/+$/, "") + url;
    return url;
  }

  /** "1:02:03" or "2:03" from milliseconds; "" for nothing sensible. */
  function formatTime(ms) {
    if (typeof ms !== "number" || !isFinite(ms) || ms < 0) return "";
    var total = Math.floor(ms / 1000);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var ss = s < 10 ? "0" + s : String(s);
    if (h) return h + ":" + (m < 10 ? "0" + m : m) + ":" + ss;
    return m + ":" + ss;
  }

  var PLAYER_ERRORS = {
    PLAYER_ERROR_CONNECTION_FAILED: "Couldn't connect to the video. It may have expired or be blocked.",
    PLAYER_ERROR_INVALID_URI: "The video address wasn't valid.",
    PLAYER_ERROR_NOT_SUPPORTED_FILE: "The TV can't play this type of video.",
    PLAYER_ERROR_NOT_SUPPORTED_FORMAT: "The TV can't play this video format.",
    PLAYER_ERROR_INVALID_OPERATION: "The TV's player got into a muddle. Try sending it again.",
    PLAYER_ERROR_INVALID_PARAMETER: "The TV's player rejected the video.",
    PLAYER_ERROR_NO_SUCH_FILE: "The video couldn't be found.",
    PLAYER_ERROR_SEEK_FAILED: "Couldn't skip to that point.",
    PLAYER_ERROR_GENEREIC: "The TV's player hit an error.",
    PLAYER_ERROR_GENERIC: "The TV's player hit an error.",
    PLAYER_ERROR_DRM_FAILED: "That video is copy-protected.",
    PLAYER_ERROR_NETWORK_DISCONNECTED: "The TV lost its network connection.",
    PLAYER_ERROR_TIMEOUT: "The video took too long to start.",
  };

  /** A short explanation of an AVPlay error, which arrives as a code string or an exception. */
  function describePlayerError(error) {
    var code = "";
    if (typeof error === "string") code = error;
    else if (error && error.name) code = error.name;
    else if (error && error.code) code = String(error.code);
    var known = PLAYER_ERRORS[code];
    if (known) return known;
    var message = error && error.message ? error.message : code;
    return message ? "The TV's player hit an error (" + message + ")." : "The TV's player hit an error.";
  }

  /** What a key press means on each screen. Returns an action name or "". */
  function keyAction(mode, keyName) {
    if (mode === "settings") {
      if (keyName === "Up" || keyName === "Down") return "move-focus";
      if (keyName === "Enter") return "activate";
      if (keyName === "Return") return "cancel";
      return "";
    }
    if (mode === "playing" || mode === "loading") {
      if (keyName === "Enter" || keyName === "MediaPlayPause") return "toggle";
      if (keyName === "MediaPlay") return "resume";
      if (keyName === "MediaPause") return "pause";
      if (keyName === "Left" || keyName === "MediaRewind") return "seek-back";
      if (keyName === "Right" || keyName === "MediaFastForward") return "seek-forward";
      if (keyName === "Up" || keyName === "Down") return "show-osd";
      if (keyName === "Return" || keyName === "MediaStop") return "stop";
      return "";
    }
    if (mode === "error") {
      if (keyName === "Enter" || keyName === "Return") return "dismiss";
      return "";
    }
    // idle
    if (keyName === "Enter") return "settings";
    if (keyName === "Return") return "exit";
    return "";
  }

  /** Map a keyCode to its name, using codes reported by the TV where available. */
  function keyName(keyCode, codes) {
    var table = codes || KEY_CODES;
    for (var name in table) {
      if (Object.prototype.hasOwnProperty.call(table, name) && table[name] === keyCode) return name;
    }
    return BROWSER_KEYS[keyCode] || "";
  }

  return {
    DEFAULT_PORT: DEFAULT_PORT,
    KEY_CODES: KEY_CODES,
    MEDIA_KEYS: MEDIA_KEYS,
    SEEK_BACK_SECONDS: SEEK_BACK_SECONDS,
    SEEK_FORWARD_SECONDS: SEEK_FORWARD_SECONDS,
    normaliseHubUrl: normaliseHubUrl,
    pickHubUrl: pickHubUrl,
    streamUrl: streamUrl,
    formatTime: formatTime,
    describePlayerError: describePlayerError,
    keyAction: keyAction,
    keyName: keyName,
  };
});
