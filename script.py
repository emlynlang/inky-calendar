import datetime
import math
import os
import requests
from PIL import Image, ImageDraw, ImageFont

# CONFIGURATION
CALENDAR_URL = os.environ.get("CALENDAR_URL")
LAT = os.environ.get("LATITUDE", "54.27").strip()   
LON = os.environ.get("LONGITUDE", "-8.47").strip()
OUTPUT_PATH = "dashboard.jpg"

# Font Loading Helper with Graceful Fallback
def get_custom_font(font_name, size):
    try:
        if font_name == "date":
            return ImageFont.truetype("fonts/Playfair.ttf", size)
        return ImageFont.truetype("fonts/Inter.ttf", size)
    except IOError:
        return ImageFont.load_default()

def get_weather():
    base_url = "https://open-meteo.com"
    query_params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "timezone": "auto"
    }
    return requests.get(base_url, params=query_params).json()

# Dynamic Weather Icon Renderer (Vector Vector Art)
def draw_weather_icon(draw, code, x, y, size=80):
    # Map WMO weather codes to generalized states
    if code in [0, 1]: # Sunny / Clear
        draw.ellipse([x, y, x+size, y+size], fill="yellow", outline="orange", width=3)
    elif code in [2, 3]: # Partly Cloudy / Overcast
        draw.ellipse([x+10, y+20, x+50, y+50], fill="blue") # Back cloud
        draw.ellipse([x+25, y+10, x+75, y+60], fill="white", outline="black", width=2)
    elif code in [51, 53, 55, 61, 63, 65, 80, 81]: # Rain / Drizzle
        draw.ellipse([x+15, y+10, x+65, y+45], fill="black") # Cloud base
        for i in range(3): # Raindrops
            rx = x + 25 + (i * 15)
            draw.line([(rx, y+55), (rx-5, y+65)], fill="blue", width=3)
    else: # Default Cloud / Unknown
        draw.ellipse([x+10, y+15, x+70, y+55], fill="black")

def get_moon_phase(year, month, day):
    if month < 3:
        year -= 1; month += 12
    month += 1
    jd = (365.25 * year) + (30.6 * month) + day - 694039.09 
    phase = (jd / 29.530588853) - int(jd / 29.530588853)
    if phase < 0.06 or phase > 0.94: return "New Moon", 0
    elif phase < 0.19: return "Waxing Crescent", 0.25
    elif phase < 0.31: return "First Quarter", 0.5
    elif phase < 0.44: return "Waxing Gibbous", 0.75
    elif phase < 0.56: return "Full Moon", 1.0
    elif phase < 0.69: return "Waning Gibbous", 0.75
    elif phase < 0.81: return "Last Quarter", 0.5
    else: return "Waning Crescent", 0.25

def draw_moon_icon(draw, illumination, x, y, size=80):
    # Draw dark background moon sphere
    draw.ellipse([x, y, x+size, y+size], fill="white", outline="black", width=2)
    if illumination > 0:
        # Draw illuminated portion using an overlapping yellow slice
        draw.chord([x, y, x+size, y+size], -90, 90, fill="yellow")

def generate_image():
    img = Image.new("RGB", (800, 480), "white")
    draw = ImageDraw.Draw(img)
    
    font_clock = get_custom_font("main", 64)
    font_date = get_custom_font("date", 24)
    font_body = get_custom_font("main", 18)
    font_sub = get_custom_font("main", 14)
    
    now = datetime.datetime.now()
    is_day = 6 <= now.hour < 18
    
    # Dividers
    draw.line([(320, 0), (320, 480)], fill="black", width=2)
    draw.line([(320, 300), (800, 300)], fill="black", width=2)
    
    # Left Panel: Modern Clock & Calendar Text
    draw.text((30, 30), now.strftime("%H:%M"), font=font_clock, fill="black")
    draw.text((30, 110), now.strftime("%A, %b %d"), font=font_date, fill="red")
    
    weather_data = get_weather()
    
    # Left Bottom Window: Dynamic Graphic Modes
    if is_day:
        current_code = weather_data["current"]["weather_code"]
        current_temp = weather_data["current"]["temperature_2m"]
        draw_weather_icon(draw, current_code, 40, 200, size=90)
        draw.text((150, 220), f"{current_temp}°C", font=font_clock, fill="blue")
    else:
        phase_name, illum = get_moon_phase(now.year, now.month, now.day)
        draw_moon_icon(draw, illum, 40, 200, size=90)
        draw.text((40, 310), phase_name, font=font_date, fill="black")
        draw.text((40, 345), f"{int(illum*100)}% Illuminated", font=font_sub, fill="blue")
        
    # Right Panel: Agenda Layout Block
    draw.text((350, 30), "TODAY'S SCHEDULE", font=font_date, fill="black")
    draw.line([(350, 65), (770, 65)], fill="red", width=2)
    
    draw.text((350, 90), "🟢  09:00   Morning Sync Meeting", font=font_body, fill="black")
    draw.text((350, 130), "⚪  12:15   Lunch with Team", font=font_body, fill="black")
    draw.text((350, 170), "🔴  14:00   Project Review Block", font=font_body, fill="black")
    
    # Bottom Panel: Horizontal 5-Day Forecast Grid
    days = ["Today", "Tomorrow", "Day +2", "Day +3", "Day +4"]
    for i in range(5):
        x_offset = 345 + (i * 90)
        day_code = weather_data["daily"]["weather_code"][i]
        day_max = weather_data["daily"]["temperature_2m_max"][i]
        day_min = weather_data["daily"]["temperature_2m_min"][i]
        
        # Grid Element Strings
        draw.text((x_offset, 320), days[i], font=font_sub, fill="black")
        draw_weather_icon(draw, day_code, x_offset, 345, size=40)
        draw.text((x_offset, 400), f"{int(day_max)}°", font=font_body, fill="red")
        draw.text((x_offset, 425), f"{int(day_min)}°", font=font_body, fill="blue")
        
    img.save(OUTPUT_PATH, "JPEG", quality=85)

if __name__ == "__main__":
    generate_image()
