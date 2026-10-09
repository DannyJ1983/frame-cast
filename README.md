# Frame Cast

Share a webpage from your phone and its video plays on the TV. Built for a 2019 Samsung Frame (QE43LS03R), which has no Chromecast.

```
phone ──share link──▶ home server (Pi) ──finds the stream──▶ TV app ──plays it on the TV's own decoder
```

- **Home server** (`framecast/`): a small Python service on a Raspberry Pi or any always-on computer. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to find the video stream inside the page and tells the TV app to play it. If a site only serves video to requests with a Referer or cookies, the server relays the stream and adds them.
- **TV app** (`tv/`): a Tizen web app that plays streams with Samsung's AVPlay player. That's the TV's hardware decoder, so HLS (including live streams), DASH and MP4 all work.
- **Phone**: share from any app with an iPhone Shortcut or the Android HTTP Shortcuts app, or paste links into the server's web page.

## What works and what doesn't

- Most pages with a plain video or a live stream: news sites, sports streams, the many sites yt-dlp supports, and direct `.m3u8`/`.mpd`/`.mp4` links.
- **Copy-protected services won't work**: Netflix, Disney+, Prime Video, NOW and the like. Use their own TV apps.
- Pages that need you signed in won't work.
- YouTube: use the TV's YouTube app and the cast button in the YouTube phone app.
- Anyone on your home WiFi can send videos to the TV. There's no password.

## 1. Run the home server

### On a Raspberry Pi

Works on a Pi 3, 4, 5 or Zero 2 W.

1. **Flash the SD card** with [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Choose your Pi model and **Raspberry Pi OS Lite (64-bit)**, under *Raspberry Pi OS (other)*. In the customisation step:
   - Hostname: `framecast`
   - Username and password: choose your own
   - WiFi: your home network's name and password, with your country
   - SSH: on, with password login
2. **Boot the Pi** and give it a couple of minutes to join the WiFi.
3. **Connect from a computer** with `ssh <your username>@framecast.local`.
4. **Run the setup:**

   ```sh
   curl -fsSL https://raw.githubusercontent.com/DannyJ1983/frame-cast/main/setup.sh | sudo bash
   ```

This downloads Frame Cast and installs the `frame-cast` service on port 8090. It takes 5 to 10 minutes on a Pi and prints the address to use at the end, such as `http://192.168.1.20:8090`. Open that address on your phone to get the web page. Run the same command again later to update.

**Fix the Pi's address.** The TV app remembers the address, so reserve it in your router's DHCP settings. On a Virgin Media Hub that's under the advanced settings, as a DHCP reservation. This stops the Pi getting a different address after a restart.

Already have the repo on the Pi? `sudo ./install.sh` from inside it does the same as the setup command.

Settings are in `/etc/frame-cast.env`. Logs: `journalctl -u frame-cast -f`.

### On a laptop, for trying it out

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m framecast --port 8090
```

Then open `http://localhost:8090` for the phone page and `http://localhost:8090/tv/` to see the TV app in your browser. The browser version uses a stand-in player that shows the stream address instead of playing it.

## 2. Put the app on the TV

You do this once, from a Windows, Mac or Linux computer on the same network. The TV doesn't need rooting.

1. **Turn on Developer Mode on the TV.** Open **Apps**, then type **1 2 3 4 5** with the remote's number buttons or the on-screen number pad. Switch **Developer mode** on and enter your computer's IP address. Then restart the TV: hold the power button until it switches off and on again.
2. **Install Tizen Studio** from the Tizen developer site. In its **Package Manager**, under **Extension SDK**, install **Samsung Certificate Extension** and the **TV Extensions** for Tizen 5.0 (2019 TVs).
3. **Connect to the TV.** Open **Tools → Device Manager → Remote Device Manager**, add the TV's IP address with port **26101**, and switch the connection on.
4. **Make a Samsung certificate.** Open **Tools → Certificate Manager**, press **+**, then choose **Samsung**, then **TV**. Name the profile (for example `frame`), create an author certificate, and sign in with a Samsung account. For the distributor certificate, choose privilege level **Public** and make sure the TV's DUID is listed. Certificate Manager fills it in from the connected TV.
5. **Build and install.** In a terminal (Git Bash on Windows), from this repo:

   ```sh
   CERT_PROFILE=frame tv/build.sh --hub http://192.168.1.20:8090 --install 192.168.1.50
   ```

   Use your server's address for `--hub` and the TV's IP for `--install`. **Frame Cast** then appears in the TV's Apps. If the script fails, do the same steps in the Tizen Studio app instead:
   1. **File → Import → Tizen → Tizen Project**, then choose the `tv` folder.
   2. Right-click the project, then choose **Run As → Tizen Web Application**.

   Built that way, the app asks for the server address the first time it opens.

Open Frame Cast on the TV. It should say **Ready. Connected to http://…**. To change the server address later, press OK on that screen.

## 3. Share from your phone

The phone must be on the home WiFi. The server's web page has these same steps, with your server's address filled in.

**iPhone** (Shortcuts app)
1. Make a new shortcut called **Send to Frame**. Under **ⓘ**, turn on **Show in Share Sheet** and set it to receive **URLs** and **Safari web pages**.
2. Add **Get Contents of URL** with:
   - URL: `http://<server>:8090/api/send`
   - Method: **POST**
   - Request body: **JSON**, with a field `url` set to **Shortcut Input**
3. Add **Show Notification** with **Contents of URL**.

**Android** (the free [HTTP Shortcuts](https://http-shortcuts.rmy.ch/) app; menu names may differ slightly between versions)
1. Create a variable `link` (type **Static**) and allow it to receive values from the **Share** dialog.
2. Create a shortcut **Send to Frame** with:
   - Method: **POST**
   - URL: `http://<server>:8090/api/send?reply=text`
   - Body: custom text `{link}`
3. Show the response as a toast, and set the timeout to 60 seconds.
4. Then, from any app: **Share → HTTP Shortcuts → Send to Frame**.

If the TV app is closed when you share, the link waits for 10 minutes and plays when you open the app.

## 4. Optional: open the app on the TV by itself

The server can switch the TV to Frame Cast when you share a link, using Samsung's local remote-control interface:

1. In `/etc/frame-cast.env`, set `FRAMECAST_TV_HOST=<the TV's IP>`, then run `sudo systemctl restart frame-cast`.
2. Run `frame-cast tv-pair` and choose **Allow** on the TV when it asks.

This hasn't been tried on the Frame yet. If the app doesn't open, run `frame-cast tv-apps` to see the app IDs the TV reports. Then set `FRAMECAST_TV_APP_ID` if Frame Cast is listed under an ID other than `FrameCast0.FrameCast`. A TV that's fully switched off can't be reached this way.

## When something doesn't play

- **Rule out the TV first.** On the server's web page, open the sharing section and press **Send a test video**. If that plays, the TV app is fine and the problem is the page.
- **"Couldn't find a video on that page"**: run `frame-cast resolve <link>` on the Pi to see what yt-dlp finds. Sites change often, so update yt-dlp with `sudo ./update-yt-dlp.sh`.
- **The TV shows "Couldn't connect to the video"**: the site may check where requests come from. Set `FRAMECAST_RELAY=always` in `/etc/frame-cast.env` and restart, so the stream goes through the Pi.
- **The TV says it can't reach the home server**: check the address on the TV's start screen (press OK to change it), and that both are on the same network.
- The phone page shows what the TV is doing, including the TV player's error messages.

## Development

```sh
.venv/bin/pytest
```

This runs about 90 tests:
- unit tests for the server
- the TV app's JavaScript tests, under Node
- a check that the TV code avoids browser features newer than the TV's Chromium 63
- browser end-to-end tests: Playwright drives the TV app with the stand-in player against a real server

`python -m framecast --help` lists the server options.

## Status

Checked here: everything except the parts that need the TV. That covers stream finding (against yt-dlp-shaped data), the relay, the server, the phone page, and the TV app's logic and screens in Chromium with the stand-in player. The Pi installer was also trial-run in a container, with systemd stubbed out.

Needs the real TV:
- AVPlay playback itself: formats, 4K mode, the user agent setting, and suspend/resume
- the remote's media keys
- the Tizen Studio build and install script
- opening the app automatically over Samsung's remote-control interface
