// Wraps Samsung's AVPlay player, which plays on the TV's own hardware decoder.
// AVPlay's states run NONE -> IDLE (open) -> READY (prepare) -> PLAYING <-> PAUSED, and
// stop() returns to IDLE. close() from any state goes back to NONE.
(function (root) {
  "use strict";
  var core = root.FrameCastCore;

  /**
   * events: { onState(state, detail), onTime(positionMs, durationMs) }
   * where state is "loading", "buffering", "playing", "paused", "ended", "stopped" or "error".
   */
  function Player(webapis, events) {
    this.webapis = webapis;
    this.avplay = webapis.avplay;
    this.events = events;
    this.state = "stopped";
    this.position = 0;
    this.duration = 0;
    this.generation = 0; // Ignores callbacks from a stream that has since been replaced.
  }

  Player.prototype._set = function (state, detail) {
    this.state = state;
    this.events.onState(state, detail || "");
    this._screenSaver(state === "playing" || state === "buffering" || state === "loading");
  };

  Player.prototype._screenSaver = function (keepAwake) {
    var appcommon = this.webapis.appcommon;
    if (!appcommon || !appcommon.setScreenSaver) return;
    try {
      var states = appcommon.AppCommonScreenSaverState;
      appcommon.setScreenSaver(keepAwake ? states.SCREEN_SAVER_OFF : states.SCREEN_SAVER_ON);
    } catch (e) {
      // Not available on every firmware; the screen saver is only a nuisance.
    }
  };

  Player.prototype._try = function (what, fn) {
    try {
      fn();
      return true;
    } catch (e) {
      console.warn("AVPlay " + what + " failed", e);
      return false;
    }
  };

  /** Open and start a stream. options: { userAgent, isLive } */
  Player.prototype.play = function (url, options) {
    var self = this;
    var opts = options || {};
    var avplay = this.avplay;
    this._closeQuietly();
    var generation = ++this.generation;
    this.position = 0;
    this.duration = 0;
    this.isLive = Boolean(opts.isLive);
    this._set("loading");

    function current() {
      return generation === self.generation;
    }

    try {
      avplay.open(url);
      avplay.setListener({
        onbufferingstart: function () {
          if (current() && self.state === "playing") self._set("buffering");
        },
        onbufferingprogress: function () {},
        onbufferingcomplete: function () {
          if (current() && self.state === "buffering") self._set("playing");
        },
        oncurrentplaytime: function (ms) {
          if (!current()) return;
          self.position = ms;
          self.events.onTime(ms, self.duration);
        },
        onstreamcompleted: function () {
          if (!current()) return;
          self._closeQuietly();
          self._set("ended");
        },
        onerror: function (type) {
          if (!current()) return;
          self._closeQuietly();
          self._set("error", core.describePlayerError(type));
        },
        onevent: function (type, data) {
          console.log("AVPlay event", type, data);
        },
        onsubtitlechange: function () {},
        ondrmevent: function () {},
      });
      avplay.setDisplayRect(0, 0, 1920, 1080);
      this._try("setDisplayMethod", function () {
        avplay.setDisplayMethod("PLAYER_DISPLAY_MODE_LETTER_BOX");
      });
      if (opts.userAgent) {
        this._try("USER_AGENT", function () {
          avplay.setStreamingProperty("USER_AGENT", opts.userAgent);
        });
      }
      if (this._isUhdPanel()) {
        // Without this AVPlay won't pick 4K streams. Must be set before prepare.
        this._try("SET_MODE_4K", function () {
          avplay.setStreamingProperty("SET_MODE_4K", "TRUE");
        });
      }
      avplay.prepareAsync(
        function () {
          if (!current()) return;
          try {
            var duration = avplay.getDuration();
            self.duration = duration > 0 && !self.isLive ? duration : 0;
            avplay.play();
            self._set("playing");
          } catch (e) {
            self._closeQuietly();
            self._set("error", core.describePlayerError(e));
          }
        },
        function (error) {
          if (!current()) return;
          self._closeQuietly();
          self._set("error", core.describePlayerError(error));
        }
      );
    } catch (e) {
      this._closeQuietly();
      this._set("error", core.describePlayerError(e));
    }
  };

  Player.prototype._isUhdPanel = function () {
    try {
      var info = this.webapis.productinfo;
      return Boolean(info && info.isUdPanelSupported && info.isUdPanelSupported());
    } catch (e) {
      return false;
    }
  };

  Player.prototype._closeQuietly = function () {
    var avplay = this.avplay;
    this._try("stop", function () {
      var state = avplay.getState();
      if (state === "PLAYING" || state === "PAUSED" || state === "READY") avplay.stop();
    });
    this._try("close", function () {
      if (avplay.getState() !== "NONE") avplay.close();
    });
  };

  Player.prototype.pause = function () {
    var self = this;
    if (this.state !== "playing" && this.state !== "buffering") return;
    if (this._try("pause", function () { self.avplay.pause(); })) this._set("paused");
  };

  Player.prototype.resume = function () {
    var self = this;
    if (this.state !== "paused") return;
    if (this._try("play", function () { self.avplay.play(); })) this._set("playing");
  };

  Player.prototype.toggle = function () {
    if (this.state === "paused") this.resume();
    else this.pause();
  };

  /** Jump by a number of seconds, forwards (positive) or back (negative). */
  Player.prototype.seek = function (seconds) {
    var avplay = this.avplay;
    if (this.state !== "playing" && this.state !== "paused" && this.state !== "buffering") return;
    var ms = Math.round(Math.abs(seconds) * 1000);
    var failed = function (e) { console.warn("Seek failed", e); };
    this._try("seek", function () {
      if (seconds >= 0) avplay.jumpForward(ms, function () {}, failed);
      else avplay.jumpBackward(ms, function () {}, failed);
    });
  };

  Player.prototype.stop = function () {
    this.generation++;
    this._closeQuietly();
    this._set("stopped");
  };

  /** Call when the app is hidden or shown again (Samsung requires apps to handle this). */
  Player.prototype.setVisible = function (visible) {
    var avplay = this.avplay;
    if (this.state === "stopped" || this.state === "ended" || this.state === "error") return;
    this._try(visible ? "restore" : "suspend", function () {
      if (visible) avplay.restore();
      else avplay.suspend();
    });
  };

  root.FrameCastPlayer = Player;
})(window);
