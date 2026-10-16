// Talks to the home server: listens for play and control commands, and reports status back.
(function (root) {
  "use strict";

  /** handlers: { onPlay(command), onControl(control), onChannels(list), onShow(screen), onConnected(), onDisconnected() } */
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
    source.addEventListener("channels", function (event) {
      self.handlers.onChannels(JSON.parse(event.data).channels || []);
    });
    source.addEventListener("show", function (event) {
      if (self.handlers.onShow) self.handlers.onShow(JSON.parse(event.data).screen);
    });
  };

  HubClient.prototype.close = function () {
    if (this.source) this.source.close();
    this.source = null;
    this.connected = false;
  };

  /** Address of the dashboard page the home server serves. */
  HubClient.prototype.dashboardUrl = function () {
    return this.hubUrl + "/dashboard/";
  };

  /** Address of a channel's logo; the version changes whenever the logo does. */
  HubClient.prototype.logoUrl = function (channel) {
    return this.hubUrl + "/api/channels/" + encodeURIComponent(channel.id) + "/logo?v=" + channel.logo_version;
  };

  /**
   * Ask the hub to find and play a saved channel. Resolves to { ok, message }; the stream itself
   * arrives as a play event. No body or custom headers, so no CORS preflight.
   */
  HubClient.prototype.playChannel = function (channelId) {
    return fetch(this.hubUrl + "/api/channels/" + encodeURIComponent(channelId) + "/play", { method: "POST" })
      .then(function (response) {
        return response.json().then(
          function (data) { return { ok: response.ok, message: data.message || "" }; },
          function () { return { ok: response.ok, message: response.statusText }; }
        );
      })
      .catch(function () {
        return { ok: false, message: "Couldn't reach the home server." };
      });
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
