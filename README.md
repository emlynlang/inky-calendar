# Inky Frame Weather & Tide Dashboard

A weather and tide display for the **Pimoroni Inky Frame 7.3"** (Pico W). A free GitHub Action draws an 800×480 picture every 30 minutes and the Inky Frame downloads and shows it.

It shows:

- Today's date and large current weather
- Sunrise and sunset
- A tide chart for today, with a red "now" marker
- A 5-day forecast
- The moon phase after sunset (next tides by day)

No server, no subscription, no API keys. Everything runs free on GitHub and Open-Meteo.

## How it works

```
GitHub Action (script.py)  -->  "dashboard" branch  -->  Inky Frame downloads and shows it
   draws dashboard.jpg          holds one commit          every 30 minutes
   + dashboard.json             (replaced each run)
```

- `script.py` fetches weather and tide data from [Open-Meteo](https://open-meteo.com/) and draws the picture using only the seven inks the panel can print.
- The workflow force-pushes the picture to a one-commit `dashboard` branch, so your repo never fills up with old pictures.
- `pico/main.py` runs on the Inky Frame. It downloads the picture, checks it is a real JPEG, draws it, adds the red "now" marker from the Pico's own clock, then waits 30 minutes. A safety timer restarts the frame if an update ever freezes (for example the Wi-Fi drops mid-download).
- GitHub's own schedule can run hours late, so a free [cron-job.org](https://cron-job.org) job triggers the workflow every 30 minutes instead.

## What you need

- Pimoroni Inky Frame 7.3" (Pico W version) with Pimoroni's Inky Frame MicroPython firmware
- A micro-USB cable and a computer with [Thonny](https://thonny.org/)
- A free GitHub account and a free cron-job.org account

## Setup

### 1. Get the code
Click **Use this template** (or fork) on GitHub and make your copy **public**. The Inky Frame downloads the picture without logging in, so the repo must be public.

### 2. Add your settings as repository secrets
In your repo: **Settings > Secrets and variables > Actions > New repository secret**.

| Secret | Example | Needed? |
|---|---|---|
| `LATITUDE` | `51.50` | Yes |
| `LONGITUDE` | `-0.12` | Yes |
| `TIMEZONE` | `Europe/London` | Yes, unless you live in Ireland |
| `TIDE_LATITUDE` | `51.45` | Yes, for tides |
| `TIDE_LONGITUDE` | `0.60` | Yes, for tides |

**Choosing the tide point:** the tide model has no data over land. Pick a spot in the sea close to your coast (use Google Maps and right-click to copy the coordinates). Try one or two points if the first gives odd times. The model is about 8 km across and can be unreliable very close to shore.

Time zone names come from [this list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

### 3. Run it once
**Actions** tab, choose **Generate E-Ink Dashboard**, **Run workflow**. When it has a green tick, the repo has a `dashboard` branch with `dashboard.jpg` and `dashboard.json`.

### 4. Put the program on the Inky Frame
1. Install Pimoroni's Inky Frame MicroPython firmware (pick the Pico W build, not the "with examples" one).
2. In Thonny, copy `pico/main.py` and `pico/secrets_example.py` to the Pico, and rename the second one to `secrets.py` on the Pico.
3. Edit `secrets.py` on the Pico:

```python
WIFI_SSID = "your wifi name"
WIFI_PASSWORD = "your wifi password"
IMAGE_URL = "https://raw.githubusercontent.com/YOUR-USER/YOUR-REPO/dashboard/dashboard.jpg"
```

4. In `main.py`, check the two time settings near the top:
   - `UTC_OFFSET_HOURS` is your winter offset from UTC (Ireland/UK: `0`, central Europe: `1`).
   - `EU_SUMMER_TIME = True` adds one hour in the European summer period. Set it to `False` if your country does not use these dates. The red marker will be an hour out if this is wrong.
5. Press the RST button on the back. After about a minute the picture appears.

### 5. Make it refresh every 30 minutes (recommended)
Create a free cron-job.org job that calls the GitHub API:

- URL: `https://api.github.com/repos/YOUR-USER/YOUR-REPO/actions/workflows/run_script.yml/dispatches`
- Method: `POST`, body `{"ref":"main"}`
- Headers: `Authorization: Bearer YOUR_TOKEN`, `Accept: application/vnd.github+json`, `Content-Type: application/json`, `X-GitHub-Api-Version: 2022-11-28`
- Success is status `204`.

Make the token a **fine-grained personal access token** limited to this one repo with only **Actions: Read and write**. Treat it like a password, and it will expire, so note the date.

## Troubleshooting

| Problem | Fix |
|---|---|
| Warning light, no new picture | Check `IMAGE_URL` (branch must be `dashboard`) and that the repo is public |
| Only updates when you switch the power off and on | Use the `main.py` here; it restarts itself after each wait |
| Screen frozen on an old picture, green "busy" light stuck on | The update froze (usually a Wi-Fi drop mid-download). The latest `main.py` has a safety timer that restarts the frame after 5 minutes. Copy it over and restart once by hand |
| Red marker an hour out | Check `UTC_OFFSET_HOURS` and `EU_SUMMER_TIME` |
| No red marker | The picture is from yesterday or the clock could not be set; it returns on the next update |
| Tide chart empty | `TIDE_LATITUDE/LONGITUDE` is on land, or the tide service had an error (see the Action log: "Tide error") |
| Action fails with "cannot pull with rebase" | You are using an older workflow; use the one in this repo |
| Looks speckled or faded | The panel only has seven inks, so the design uses only those; don't edit colours to pastels |

## Notes and credits

- Weather and tide data: [Open-Meteo](https://open-meteo.com/) (free for non-commercial use, CC BY 4.0, attribution required).
- **Tide data is a computer-model estimate. Times only, no heights above chart datum. Do not use it for navigation, fishing safety or any safety decision.** Use official tide tables.
- Font: Inter (SIL Open Font License), downloaded by the Action. If the download fails, a fallback font is used.
- Moon phase is calculated locally from the synodic month.
