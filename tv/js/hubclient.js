// Talks to the home server: listens for play and control commands, and reports status back.
(function (root) {
  "use strict";

  /** handlers: { onPlay(command), onControl(control), onConnected(), onDisconnected() } */
  function HubClient(hubUrl, handlers) {
    this.hubUrl = hubUrl.replace(/\/+$/, "");
    this.handlers = handlers;
    this.source = null;
    this.connected = false;
  }

  HubClient.prototype.connect = function () {
    var self = this;
    this.close();
    // EventSource reconnects by itself after a dropped connection.
    var source = new EventSource(this.hubUrl + "/api/tv/events");
    this.source = source;
    source.onopen = function () {
      self.connected = true;
      self.handlers.onConnected();
    };
    source.onerror = function () {
      self.connected = false;
      self.handlers.onDisconnected();
    };
    source.addEventListener("play", function (event) {
      self.handlers.onPlay(JSON.parse(event.data));
    });
    source.addEventListener("control", function (event) {
      self.handlers.onControl(JSON.parse(event.data));
    });
  };

  HubClient.prototype.close = function () {
    if (this.source) this.source.close();
    this.source = null;
    this.connected = false;
  };

  /** Send a status report. Plain text so the browser doesn't need a CORS preflight. */
  HubClient.prototype.report = function (status) {
    try {
      fetch(this.hubUrl + "/api/tv/status", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify(status),
      }).catch(function () {});
    } catch (e) {
      // Reporting is best effort.
    }
  };

  root.FrameCastHubClient = HubClient;
})(window);
