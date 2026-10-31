# A Weather and Tide Display for the Inky Frame (No Server Needed)

## Introduction

I wanted a calm, always-on display that tells me the weather and the tides at a glance, like a small picture frame on the wall. The result runs on a Pimoroni Inky Frame 7.3" colour e-ink screen, costs nothing to run, and needs no server of your own.

It shows today's date, a big current-weather icon, sunrise and sunset, a tide chart with a red marker for "now", a 5-day forecast, and the phase of the moon after dark.

**How it works in one minute:** a free GitHub Action draws an 800×480 picture every 30 minutes from free Open-Meteo data. The Inky Frame downloads that picture and puts it on the screen. All the clever drawing happens on GitHub, so the little Pico on the frame only has to download and display.

*(Photo: finished display on the wall)*

## Supplies

- Pimoroni Inky Frame 7.3" (the Pico W version)
- Micro-USB cable and a computer (Windows, Mac or Linux)
- Thonny (free) to copy files to the Pico
- A free GitHub account
- A free cron-job.org account (optional but recommended)
- A Wi-Fi network (2.4 GHz)

*(Photo: parts laid out)*

## Step 1: A Quick Word on the Screen

The 7.3" panel can print only seven pure inks: black, white, green, blue, red, yellow and orange. Photos and soft pastel colours turn into speckles. So the picture is drawn using only those inks, with hard edges and cartoon-style icons with black outlines. The light-blue sea is drawn as thin blue stripes on white. If you change the design, stick to those seven colours.

## Step 2: Get the Code

1. Go to the project's GitHub page and click **Use this template** to make your own copy.
2. Make your copy **Public**. The Inky Frame downloads the picture without logging in, so it has to be public.

*(Screenshot: Use this template button)*

## Step 3: Tell It Where You Live

In your repo go to **Settings > Secrets and variables > Actions** and add these secrets:

- `LATITUDE` and `LONGITUDE`: your location
- `TIMEZONE`: for example `Europe/London`
- `TIDE_LATITUDE` and `TIDE_LONGITUDE`: a point in the **sea** near you

The tide model has no data over land, so for the tide point use a spot just offshore (right-click in Google Maps to copy coordinates). If the tide times look wrong, try a different spot a little further out.

*(Screenshot: secrets page)*

## Step 4: Run It Once

Open the **Actions** tab, choose **Generate E-Ink Dashboard**, then **Run workflow**. After about a minute you get a green tick, and your repo has a new branch called `dashboard` containing `dashboard.jpg`.

Each run replaces that branch with a single new commit. That way your repo never fills up with hundreds of old pictures.

*(Screenshot: green tick, and the dashboard branch)*

## Step 5: Install the Inky Frame Firmware

1. Download Pimoroni's Inky Frame MicroPython firmware. Choose the **Pico W** build, and not the "with examples" version.
2. Hold the BOOTSEL button on the Pico (on the back of the frame), plug in the micro-USB cable, then let go. A drive called **RPI-RP2** appears.
3. Drag the .uf2 firmware file onto it. The frame restarts.

*(Photo: BOOTSEL button)*

## Step 6: Copy the Program to the Frame

1. Open Thonny and choose the MicroPython (Raspberry Pi Pico) interpreter at the bottom right.
2. Copy `main.py` and `secrets_example.py` from the `pico` folder of the project onto the Pico. Rename `secrets_example.py` to `secrets.py` on the Pico (right-click it in Thonny's file list).
3. Open `secrets.py` on the Pico and fill in:

```python
WIFI_SSID = "your wifi name"
WIFI_PASSWORD = "your wifi password"
IMAGE_URL = "https://raw.githubusercontent.com/YOUR-USER/YOUR-REPO/dashboard/dashboard.jpg"
```

4. At the top of `main.py`, set `UTC_OFFSET_HOURS` (your winter offset from UTC; 0 for the UK and Ireland) and `EU_SUMMER_TIME` (`True` for Europe, `False` if your country doesn't use those dates). This only affects the red "now" marker.
5. Press the RST button. After about a minute the picture appears.

*(Screenshot: Thonny with the files)*

## Step 7: Make It Refresh Every 30 Minutes

GitHub's own schedule can run hours late, so I use a free timer on cron-job.org to start the workflow exactly when I want.

1. On GitHub: **Settings > Developer settings > Personal access tokens > Fine-grained tokens**. Create a token for **only this repo**, with **Actions: Read and write**. Copy it and keep it private, like a password. It expires, so note the date.
2. On cron-job.org create a job every 30 minutes with:

| Setting | Value |
|---|---|
| URL | `https://api.github.com/repos/YOUR-USER/YOUR-REPO/actions/workflows/run_script.yml/dispatches` |
| Method | POST |
| Body | `{"ref":"main"}` |
| Header: Authorization | `Bearer YOUR_TOKEN` |
| Header: Accept | `application/vnd.github+json` |
| Header: Content-Type | `application/json` |
| Header: X-GitHub-Api-Version | `2022-11-28` |

3. Press **Test run**. Status `204` means it worked. If you see `301`, you have mistyped the URL, so paste it again exactly.

*(Screenshot: cron-job.org settings with the token hidden)*

## Step 8: The Red "Now" Marker

You may wonder why a red dot sits on the tide curve. The picture can be slightly old, so the frame draws the dot itself, using the time from the internet. That means it is correct every time the screen refreshes. If the picture is from yesterday, or the clock can't be set, the frame simply leaves the marker off.

## Step 9: The Safety Timer (Why It Fixes Itself)

Once, my frame froze for more than a day. It was stuck on yesterday's picture with the green "busy" light still on. The likely cause was a Wi-Fi drop in the middle of a download: the Pico waited forever for data that never came, and only switching it off and on got it going again.

The program now starts a stopwatch every time it begins an update. A normal update takes about a minute. If the stopwatch reaches five minutes, the program must be stuck, so the Pico restarts itself and tries again. When an update finishes, the stopwatch is switched off. The whole thing is a few lines in `main.py`, and the file is commented so you can follow it. The limit is the `UPDATE_TIME_LIMIT_MINUTES` setting at the top.

## Troubleshooting

- **Orange warning light, no new picture:** check `IMAGE_URL` (the branch name must be `dashboard`) and that your repo is public.
- **Only updates when you power it off and on:** the program restarts itself after every wait, and a safety timer restarts it if it freezes (see Step 9). Make sure you are using the project's latest `main.py`.
- **Stuck on an old picture with the green light on:** the update froze. Restart it once with the RST button and make sure you have the latest `main.py`.
- **Red dot an hour out:** check the two time settings in Step 6.
- **Tide chart empty:** your tide point is probably on land. Move it out to sea.
- **Action fails with "cannot pull with rebase":** you have an older workflow file. Use the one in the project.

## Good to Know

- Weather and tide data come from Open-Meteo, which is free for non-commercial use and requires credit (CC BY 4.0).
- **The tide data is a computer-model estimate. It shows times only, not heights, and it can be off close to the coast. Don't use it for navigation, boating or any safety decision. Use official tide tables.**
- A refresh every 30 minutes is gentle on the e-ink screen. Don't go much faster.
- Power use is low because the frame sleeps between updates (on battery). On USB it simply waits.

## Ideas to Take It Further

- Change the layout, or put different data in the panels
- Add your own location names and moon phase panel colours
- Use the front buttons to switch between screens

Enjoy, and if you build one, please share a photo!
