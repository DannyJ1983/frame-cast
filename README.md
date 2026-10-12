# Frame Cast

Share a webpage from your phone and its video plays on the TV. Built for a 2019 Samsung Frame (QE43LS03R), which has no Chromecast.

```
phone ──share link──▶ home server (Pi) ──finds the stream──▶ TV app ──plays it on the TV's own decoder
```

- **Home server** (`framecast/`): a small Python service on a Raspberry Pi or any always-on computer. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to find the video stream inside the page and tells the TV app to play it. For pages yt-dlp doesn't know, where the player is built by JavaScript as on many live TV sites, it opens the page in a hidden Chromium and catches the stream the player asks for, skipping ads. If a site only serves video to requests with a Referer or cookies, the server relays the stream and adds them.
- **TV app** (`tv/`): a Tizen web app that plays streams with Samsung's AVPlay player. That's the TV's hardware decoder, so HLS (including live streams), DASH and MP4 all work.
- **Phone**: share from any app with an iPhone Shortcut or the Android HTTP Shortcuts app, or paste links into the server's web page.

## What works and what doesn't

- Most pages with a plain video or a live stream: news sites, sports streams, free live TV sites, the many sites yt-dlp supports, and direct `.m3u8`/`.mpd`/`.mp4` links.
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

You do this once, from a Windows, Mac or Linux computer. The TV doesn't need rooting.

These are the steps that worked on a 2019 Frame (QE43LS03R) from a Mac. They use Samsung's command-line tools only: Tizen Studio is retired, and no VS Code or Samsung account was needed.

**The computer and the TV must be on the same network.** If your home has mesh WiFi plugged into the Virgin Hub, the two can end up on different networks. Check both IP addresses start the same way, for example 192.168.0. If not, join the computer to the TV's WiFi for the install.

1. **Install the Tizen SDK.** Download **Tizen SDK 10 with CLI** from the [Tizen tools page](https://samsungtizenos.com/tools-download/), then run it from a terminal:

   ```sh
   chmod +x ~/Downloads/web-cli_Tizen_SDK_10.0_*.bin
   ~/Downloads/web-cli_Tizen_SDK_10.0_*.bin
   ```

   On a Mac with an Apple chip, "Bad CPU type in executable" means you need Rosetta first: run `softwareupdate --install-rosetta --agree-to-license` and then run the installer again. The installer puts the tools in `~/tizen-studio`.

2. **Put the tools on your PATH:**

   ```sh
   echo 'export PATH="$HOME/tizen-studio/tools/ide/bin:$HOME/tizen-studio/tools:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```

3. **Make a certificate.** A plain Tizen certificate was enough for the 2019 Frame. Use your own password, letters and numbers only:

   ```sh
   tizen certificate -a framecast -p YourPassword -c GB -n FrameCast -f framecast
   tizen security-profiles add -n framecast -a ~/tizen-studio-data/keystore/author/framecast.p12 -p YourPassword
   tizen cli-config "profiles.path=$HOME/tizen-studio-data/profile/profiles.xml"
   ```

   Newer TVs may refuse a plain Tizen certificate. They need a Samsung certificate, made with the Certificate Manager in the Tizen extension for VS Code.

4. **Turn on Developer Mode on the TV.**
   1. Press Home, open **Apps**, and type **1 2 3 4 5**. On a remote without number buttons, the **123** button brings up a number pad.
   2. Switch **Developer mode** on and enter your computer's IP address.
   3. **Restart the TV by unplugging it at the wall for 30 seconds.** On The Frame, the power button only switches to Art Mode, and the setting doesn't take effect until a real restart.
   4. Check that **Developer Mode** now shows at the top of the Apps screen. Then check that `nc -vz <TV's IP> 26101` says "succeeded".

5. **Build and install.** From this repo (or the unzipped download from GitHub):

   ```sh
   CERT_PROFILE=framecast bash tv/build.sh --hub http://<server's IP>:8090 --install <TV's IP>
   ```

   **Frame Cast** then appears in the TV's Apps.

Open Frame Cast on the TV. It should say **Ready. Connected to http://…**. To change the server address later, press OK on that screen. To update the app, run step 5 again with the computer back on the TV's network and Developer Mode still on.

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
3. Show the response as a toast, and set the timeout to 90 seconds.
4. Then, from any app: **Share → HTTP Shortcuts → Send to Frame**.

If the TV app is closed when you share, the link waits for 10 minutes and plays when you open the app.

## 4. Optional: open the app on the TV by itself

The server can switch the TV to Frame Cast when you share a link, using Samsung's local remote-control interface:

1. In `/etc/frame-cast.env`, set `FRAMECAST_TV_HOST=<the TV's IP>`, then run `sudo systemctl restart frame-cast`.
2. Run `frame-cast tv-pair` and choose **Allow** on the TV when it asks.

This hasn't been tried on the Frame yet. If the app doesn't open, run `frame-cast tv-apps` to see the app IDs the TV reports. Then set `FRAMECAST_TV_APP_ID` if Frame Cast is listed under an ID other than `FrameCast0.FrameCast`. A TV that's fully switched off can't be reached this way.

## Saved channels

On the phone page, **Channels → Add** saves a channel: a name, the link to its page, and optionally a logo picture from your phone. While something's playing, **Save as a channel** fills in the form for you. Channels show up on the TV's start screen as a grid:
- Pick one with the arrows and press **OK**.
- While a saved channel is playing, **CH+ / CH−** move to the next or previous channel.
- **Back** stops and returns to the grid.

A channel keeps its page link rather than the stream address, because stream addresses expire, so it always finds the current stream. A stream found in the last five minutes is reused, so flicking between channels is quick. Channels and logos are kept on the Pi in `/var/lib/frame-cast`.

## When something doesn't play

- **Rule out the TV first.** On the server's web page, open the sharing section and press **Send a test video**. If that plays, the TV app is fine and the problem is the page.
- **"Couldn't find a video on that page"**: run `frame-cast resolve <link>` on the Pi to see what it finds, and `frame-cast sniff <link>` to list everything the hidden browser saw on the page. Sites change often, so update yt-dlp with `sudo ./update-yt-dlp.sh`. If the hidden browser isn't working at all, check Chromium is installed with `chromium --version`.
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

Checked on the real TV (2019 Frame, QE43LS03R):
- building, signing and installing with `tv/build.sh` and a plain Tizen certificate, from a Mac
- playback through AVPlay: a live HLS stream (a Tubi channel found on famelack by the hidden browser) and a Twitter clip at full quality

Not yet confirmed on the TV:
- every remote-control key, and suspend/resume when switching apps
- 4K streams
- opening the app automatically over Samsung's remote-control interface
