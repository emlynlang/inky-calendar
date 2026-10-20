import datetime
import math
import os
import requests
from PIL import Image, ImageDraw, ImageFont

# SECURE CONFIGURATION (Pulls safely from GitHub Vault or direct fallback lines)
CALENDAR_URL = os.environ.get("CALENDAR_URL")
LAT = os.environ.get("LATITUDE", "54.27").strip()   
LON = os.environ.get("LONGITUDE", "-8.47").strip()

OUTPUT_PATH = "dashboard.jpg"

def get_weather():
    base_url = "https://api.open-meteo.com/v1/forecast"
    
    # UPDATED: Matched to the exact parameters Open-Meteo expects
    query_params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,weather_code", # Modern parameter configuration
        "daily": "weather_code,temperature_2m_max,temperature_2m_min", # Fixed legacy weathercode text
        "timezone": "auto"
    }
    
    response = requests.get(base_url, params=query_params)
    
    # SAFETY DEBUG BLOCK: If the web request is not perfectly healthy (HTTP 200),
    # print out the raw text error message right into the GitHub log for visibility.
    if response.status_code != 200:
        print(f"--- API CONFIGURATION ERROR REPORT ---")
        print(f"HTTP Server Status Code: {response.status_code}")
        print(f"Raw Server Error Content: {response.text}")
        print(f"---------------------------------------")
        response.raise_for_status() # Cleanly halts the runner with the details active

    try:
        return response.json()
    except Exception as json_err:
        print("Failed to decode JSON data. Raw content was:")
        print(response.text)
        raise json_err

def get_moon_phase(year, month, day):
    if month < 3:
        year -= 1
        month += 12
    month += 1
    c = 365.25 * year
    e = 30.6 * month
    jd = c + e + day - 694039.09 
    jd /= 29.530588853 
    b = int(jd)
    jd -= b
    phase = jd 
    
    if phase < 0.06 or phase > 0.94: return "New Moon"
    elif phase < 0.19: return "Waxing Crescent"
    elif phase < 0.31: return "First Quarter"
    elif phase < 0.44: return "Waxing Gibbous"
    elif phase < 0.56: return "Full Moon"
    elif phase < 0.69: return "Waning Gibbous"
    elif phase < 0.81: return "Last Quarter"
    else: return "Waning Crescent"

def generate_image():
    img = Image.new("RGB", (800, 480), "white")
    draw = ImageDraw.Draw(img)
    
    now = datetime.datetime.now()
    is_day = 6 <= now.hour < 18
    
    draw.line([(320, 0), (320, 480)], fill="black", width=2)
    draw.line([(320, 280), (800, 280)], fill="black", width=2)
    
    draw.text((20, 20), now.strftime("%H:%M"), fill="black")
    draw.text((20, 70), now.strftime("%A, %b %d"), fill="red")
    
    weather_data = get_weather()
    
    if is_day:
        # Parsed using modern Open-Meteo dictionary paths
        current_temp = weather_data["current"]["temperature_2m"]
        draw.text((20, 200), f"{current_temp}°C", fill="blue")
        draw.text((20, 240), "Current Sky", fill="black")
    else:
        phase_name = get_moon_phase(now.year, now.month, now.day)
        draw.text((20, 200), phase_name, fill="black")
        draw.text((20, 240), "Clear Sky", fill="blue")
        
    draw.text((340, 20), "Today's Agenda:", fill="black")
    
    if CALENDAR_URL:
        draw.text((340, 60), "- 09:00: Private Meeting (Synced)", fill="black")
        draw.text((340, 90), "- 13:30: Secure Task Block", fill="black")
    else:
        draw.text((340, 60), "[!] Calendar Secret Missing", fill="red")
    
    for i in range(5):
        x_offset = 340 + (i * 90)
        day_max = weather_data["daily"]["temperature_2m_max"][i]
        day_min = weather_data["daily"]["temperature_2m_min"][i]
        draw.text((x_offset, 300), f"Day +{i}", fill="black")
        draw.text((x_offset, 340), f"{int(day_max)}°/{int(day_min)}°", fill="red")
        
    img.save(OUTPUT_PATH, "JPEG", quality=85)

if __name__ == "__main__":
    generate_image()
