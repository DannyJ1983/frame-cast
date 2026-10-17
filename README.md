# Frame Cast

Share a webpage from your phone and its video plays on the TV. Built for a Samsung Frame (QE43LS03T, the 2020 model), which has no Chromecast.

```
phone ──share link──▶ home server (Pi) ──finds the stream──▶ TV app ──plays it on the TV's own decoder
```

- **Home server** (`framecast/`): a small Python service on a Raspberry Pi or any always-on computer. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to find the video stream inside the page and tells the TV app to play it. For pages yt-dlp doesn't know, where the player is built by JavaScript as on many live TV sites, it opens the page in a hidden Chromium and catches the stream the player asks for, skipping ads. If a site only serves video to requests with a Referer or cookies, the server relays the stream and adds them.
- **TV app** (`tv/`): a Tizen web app that plays streams with Samsung's AVPlay player. That's the TV's hardware decoder, so HLS (including live streams), DASH and MP4 all work. It opens on a **dashboard** with the time, weather, train and bus departures, traffic, headlines and a sports ticker.
- **Phone**: share from any app with an iPhone Shortcut or the Android HTTP Shortcuts app, or paste links into the server's web page.

## What works and what doesn't

- Most pages with a plain video or a live stream: news sites, sports streams, free live TV sites, the many sites yt-dlp supports, and direct `.m3u8`/`.mpd`/`.mp4` links.
- **Copy-protected services won't work**: Netflix, Disney+, Prime Video, NOW and the like. Use their own TV apps.
- Pages that need you signed in won't work.
- YouTube: the TV's own YouTube app is best, with the cast button in the YouTube phone app. Shared YouTube links do play, in the video's original language rather than an AI dub.
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

These are the steps that worked on a 2020 Frame (QE43LS03T) from a Mac. They use Samsung's command-line tools only: Tizen Studio is retired, and no VS Code or Samsung account was needed.

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

3. **Make a certificate.** A plain Tizen certificate was enough for the 2020 Frame. Use your own password, letters and numbers only:

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

Open Frame Cast on the TV. It opens on the dashboard. Press OK to get to your channels, where the top line should say **Ready. Connected to http://…**. To change the server address later, choose the **Server address** tile there. To update the app, run step 5 again with the computer back on the TV's network and Developer Mode still on.

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

On the phone page, **Channels → Add** saves a channel: a name, the link to its page, and optionally a logo picture from your phone. While something's playing, **Save as a channel** fills in the form for you. On the TV, press **OK** on the dashboard to see your channels as a grid:
- Pick one with the arrows and press **OK**.
- While a saved channel is playing, **CH+ / CH−** move to the next or previous channel.
- **Back** stops and returns to the grid. **Back** on the grid goes to the dashboard, and so does leaving the grid alone for two minutes.

A channel keeps its page link rather than the stream address, because stream addresses expire, so it always finds the current stream. A stream found in the last five minutes is reused, so flicking between channels is quick. Channels and logos are kept on the Pi in `/var/lib/frame-cast`.

## The dashboard

The TV app opens on a dashboard served by the Pi:
- the time and date
- the weather now and for the next 12 hours
- departures from your station
- buses from your stops, with live times where the buses are tracked
- how long your drive will take in today's traffic
- news headlines
- a sports ticker with live scores, results and fixtures

Set it up on the phone page under **Dashboard → Dashboard settings**. Then **Show on TV** puts it on screen, even over a video. **Open here** shows it on your phone or laptop.

| Card | Needs | Where it comes from |
|---|---|---|
| Weather | Your postcode or town | [Open-Meteo](https://open-meteo.com), free, no key. Postcodes are looked up with [postcodes.io](https://postcodes.io). |
| Trains | Your station's three-letter code, and a free key | National Rail's live departures, through the [Rail Data Marketplace](https://raildata.org.uk). Sign up, subscribe to **Live Departure Board**, and copy the consumer key from its Specification tab. |
| Buses | Your stop codes (up to three) | The Bus Open Data Service: every operator's timetable, and with a free key, live bus positions. On buses.co.uk, a stop's code is the number at the end of its page's address. |
| Traffic | Where you drive to, and a free key | [TomTom](https://developer.tomtom.com) routing with live traffic. The drive starts from your postcode. |
| Headlines | Nothing (BBC News by default) | Any BBC News section, The Guardian, Sky News, or the address of any RSS feed. |
| Sport | Leagues to follow (the Premier League by default) | ESPN's scoreboards, with BBC Sport headlines when no matches are on. Name your teams to pick their matches out. |

**Bus times in more detail.** The government's Bus Open Data Service publishes every operator's timetable, and the live GPS position of every bus. There's no feed of arrival times for each stop, so the Pi works them out:
- The first time, it downloads your region's timetable. That's a few hundred megabytes and takes a few minutes; it's refreshed weekly. It keeps just the journeys calling at your stops. The region is worked out from your postcode, or you can pick it.
- Without a key, the card shows timetabled times.
- With a free key from [data.bus-data.dft.gov.uk](https://data.bus-data.dft.gov.uk), it matches each bus's position to its journey, works out how late it's running, and shows live minutes (with a green dot) for the buses it can place. The method follows the [BODS Bus Tracker for Home Assistant](https://github.com/IainPHay/home-assistant-bods-bus-tracker). These are estimates, not the operator's own predictions, so they can differ from the stop's display.

A card that isn't set up is left off. Cards are only fetched while the dashboard is on screen: buses every 30 seconds, trains and live scores every minute, traffic every 5 minutes, and the weather every 15. If a source stops answering, its card keeps the last good data and says it couldn't update. The keys are kept on the Pi in `/var/lib/frame-cast/dashboard.json`, readable only by the Frame Cast service, and are never sent back to the phone page.

The dashboard page comes from the Pi, so changes to it arrive with a Pi update. A dashboard already open on the TV reloads itself. Only the step from the app into the dashboard needs the TV app, so that's the one reinstall it takes.

ESPN's scoreboards aren't an official public service. If the ticker goes quiet after an ESPN change, the rest of the dashboard carries on.

## Departures board for the hallway

`http://<server>:8090/board` shows just the next buses and trains, the time and the weather, in large type. It's for a tablet, an old phone or an Amazon Echo Show by the front door, and it uses the same settings as the dashboard.

On an **Echo Show**:
1. Say "Alexa, open Silk" to open its web browser.
2. Go to `http://192.168.0.236:8090/board` (your server's address) and bookmark it for next time.
3. Tap **Tap to keep this on screen**.

The Echo Show's browser normally goes back to the home screen after a few minutes unless something is playing. So that tap starts a silent sound on a loop, the workaround the [Keep Silk Open](https://github.com/DaGammla/keep-silk-open) project found. It was tested mainly on an Echo Show 5, and Amazon's updates can change this behaviour, so it may not hold on every model.

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

This runs:
- unit tests for the server, including the dashboard's data sources against sample answers
- the TV app's JavaScript tests, under Node
- a check that the TV code avoids browser features newer than the TV's Chromium 63
- browser end-to-end tests: Playwright drives the TV app with the stand-in player against a real server

`python -m framecast --help` lists the server options.

The app icon is drawn in `scripts/render_icons.py`. After changing it, run `.venv/bin/python scripts/render_icons.py` to re-render the TV icon and the phone page's icons.

## Status

Checked here: everything except the parts that need the TV. That covers stream finding (against yt-dlp-shaped data), the relay, the server, the phone page, and the TV app's logic and screens in Chromium with the stand-in player. The Pi installer was also trial-run in a container, with systemd stubbed out.

Checked on the real TV (2020 Frame, QE43LS03T):
- building, signing and installing with `tv/build.sh` and a plain Tizen certificate, from a Mac
- playback through AVPlay: a live HLS stream (a Tubi channel found on famelack by the hidden browser) and a Twitter clip at full quality

Not yet confirmed on the TV:
- the dashboard inside the TV app (it's a page from the Pi in a frame), and its remote keys
- the live train, bus and traffic services, which need your own keys; they're built to their documentation and tested against sample answers
- the bus timetable download for a real region, and live bus estimates against real buses
- keeping the departures board on screen on an Echo Show
- every remote-control key, and suspend/resume when switching apps
- 4K streams
- opening the app automatically over Samsung's remote-control interface
