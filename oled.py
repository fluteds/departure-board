#!/usr/bin/env python3
# Norwegian Tram/Bus Departure Board on SSD1322 OLED

import os
import platform
import datetime
import time
import requests
import json
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

device = None

def running_on_pi() -> bool:
    """Rough check: Raspberry Pi is Linux + ARM."""
    try:
        return (
            platform.system() == "Linux"
            and os.uname().machine.startswith("arm")
        )
    except AttributeError:
        return False

try:
    # Only available on the Pi / when installed
    from luma.core.interface.serial import spi
    from luma.oled.device import ssd1322
except ImportError:
    spi = None
    ssd1322 = None

if running_on_pi() and spi is not None and ssd1322 is not None:
    # Try to use the real SSD1322 on SPI
    try:
        serial = spi(device=0, port=0, gpio_DC=24, gpio_RST=25)
        device = ssd1322(serial)
        print("Using real SSD1322 on Raspberry Pi")
    except Exception as e:
        print("Failed to init real SSD1322, will try emulator:", e)

if device is None:
    # Fall back to an emulator (for Mac / dev)
    try:
        from luma.emulator.device import pygame as EmulatorDevice
    except ImportError as e:
        raise SystemExit(
            "luma.emulator is not installed.\n"
            "On your Mac, run:\n\n"
            "    pip install luma.emulator\n"
        ) from e

    # Adjust resolution to match your actual panel (likely 256x64)
    device = EmulatorDevice(width=256, height=64, mode="RGB")
    print("Using OLED emulator window (no real hardware)")

# ----------------------------
#   Font loading (Entur)
# ----------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "fonts", "Entur-Nationale-Regular.ttf")

try:
    FONT = ImageFont.truetype(FONT_PATH, 12)
    FONT_ICON = ImageFont.truetype(FONT_PATH, 18)
    print(f"Loaded Entur Nationale font from {FONT_PATH}")
except Exception as e:
    print(f"Failed to load Entur font ({e}), falling back to default")
    try:
        FONT = ImageFont.load_default()
        FONT_ICON = FONT
    except Exception:
        FONT = None
        FONT_ICON = None

# ----------------------------
#   Entur API setup
# ----------------------------

CONFIG_PATH = os.path.join(SCRIPT_DIR, "config", "config.json")

config = {}
try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    print(f"Loaded config from {CONFIG_PATH}")
except Exception as e:
    print(f"Failed to load config ({e}), using defaults")
    config = {
        "stops": [
            {"id": "NSR:StopPlace:41939", "name": "Tram Stop", "type": "tram"},
            {"id": "NSR:StopPlace:41936", "name": "Bus Stop", "type": "bus"}
        ],
        "api": {
            "baseUrl": "https://api.entur.io/journey-planner/v3/graphql",
            "clientName": "fluted-departureboard"
        },
        "settings": {
            "numberOfDepartures": 3,
            "refreshInterval": 30000,
            "timezone": "Europe/Oslo"
        }
    }

URL = config.get("api", {}).get("baseUrl", "https://api.entur.io/journey-planner/v3/graphql")
HEADERS = {
    "Content-Type": "application/json",
    "ET-Client-Name": config.get("api", {}).get("clientName", "fluted-departureboard")
}

def fetch_departures(stop_id):
    num_departures = config.get("settings", {}).get("numberOfDepartures", 3)
    query = f"""
    {{
        stopPlace(id: "{stop_id}") {{
            name
            estimatedCalls(numberOfDepartures: {num_departures}) {{
                expectedArrivalTime
                aimedArrivalTime
                realtime
                destinationDisplay {{ frontText }}
                serviceJourney {{ line {{ publicCode transportMode }} }}
            }}
        }}
    }}
    """

    try:
        r = requests.post(URL, headers=HEADERS, json={"query": query}, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Check for GraphQL errors
        if "errors" in data:
            print(f"GraphQL error for {stop_id}: {data['errors']}")
            return ("Error", [])
        
        stop_place = data["data"]["stopPlace"]
        if stop_place is None:
            print(f"Stop {stop_id} not found in API")
            return ("Not Found", [])
        
        stop_name = stop_place.get("name", "Unknown Stop")
        calls = stop_place["estimatedCalls"]
        # Filter out any entries without an expectedArrivalTime
        filtered_calls = [c for c in calls if c.get("expectedArrivalTime")]
        return (stop_name, filtered_calls)
    except Exception as e:
        print(f"Error fetching departures for {stop_id}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return ("Error", [])

# ----------------------------
#   Drawing and main loop
# ----------------------------

def get_all_departures(tz, now_utc):
    """Fetch departures for all configured stops and return (deps, stop_infos)."""
    stops = config.get("stops", [])
    deps = []
    stop_infos = []
    for stop in stops:
        stop_name, calls = fetch_departures(stop["id"])
        if stop_name in ("Not Found", "Error"):
            continue

        # Determine next arrival for this stop
        next_info = ""
        try:
            if calls:
                earliest = min(c["expectedArrivalTime"] for c in calls if c.get("expectedArrivalTime"))
                t_exp = datetime.datetime.fromisoformat(earliest.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
                mins = max(int((t_exp - now_utc).total_seconds() / 60), 0)
                try:
                    t_local = datetime.datetime.fromisoformat(earliest.replace("Z", "+00:00")).astimezone(tz)
                    time_str = t_local.strftime("%H:%M")
                except Exception:
                    time_str = "--:--"
                next_info = f"{mins}m {time_str}"
        except Exception:
            next_info = ""

        if next_info:
            stop_infos.append(f"{stop_name} {next_info}")
        else:
            stop_infos.append(stop_name)

        deps.extend(calls)

    try:
        deps.sort(key=lambda d: d.get("expectedArrivalTime") or "")
    except Exception:
        pass

    return deps, stop_infos


def draw_board(deps, stop_infos, tz):
    # Match the working checkerboard: use device.mode and device.size
    image = Image.new(device.mode, device.size)
    draw = ImageDraw.Draw(image)

    # Clear background
    draw.rectangle((0, 0, device.width - 1, device.height - 1), fill=0)

    # Header with current time (local, including seconds) - positioned at top right
    try:
        now_local = datetime.datetime.now(tz).strftime("%H:%M:%S")
    except Exception:
        now_local = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")

    # Capture UTC once for consistent minute calculations
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Get text bounding box to right-align the time
    time_bbox = draw.textbbox((0, 0), now_local, font=FONT)
    time_width = time_bbox[2] - time_bbox[0]
    time_x = device.width - time_width - 5  # 5 pixels from right edge
    draw.text((time_x, 5), now_local, fill=255, font=FONT)

    # Draw title on left with fetched stop location(s) + next arrival
    header_text = " / ".join(stop_infos) if stop_infos else "Departure Board"
    # Truncate if too long for display
    header_text = header_text[:40]
    draw.text((5, 5), header_text, fill=255, font=FONT)

    # Calculate delays: find any routes with delays (expected != aimed time)
    delayed_routes = set()
    for dep in deps:
        try:
            aimed = dep.get("aimedArrivalTime")
            expected = dep.get("expectedArrivalTime")
            if aimed and expected:
                t_aim = datetime.datetime.fromisoformat(aimed.replace("Z", "+00:00"))
                t_exp = datetime.datetime.fromisoformat(expected.replace("Z", "+00:00"))
                if t_exp > t_aim:  # Delayed
                    line = dep["serviceJourney"]["line"]["publicCode"]
                    delayed_routes.add(line)
        except Exception:
            pass

    # Display delay summary if there are any delays
    y = 20
    if delayed_routes:
        delayed_text = f"Delays: {', '.join(sorted(delayed_routes))}"
        draw.text((5, y), delayed_text, fill=255, font=FONT)
        y = 32  # Adjust starting Y for departures
    else:
        y = 25  # Normal starting Y if no delays

    # Grid layout columns
    col_mode_x = 5       # Mode (Tram/Buss)
    col_line_x = 35      # Line number
    col_dest_x = 65      # Destination
    col_time_x = 200     # Time (right-aligned)

    # Draw up to configured departures
    num_display = config.get("settings", {}).get("numberOfDepartures", 3)
    for dep in deps[:num_display]:
        line = dep["serviceJourney"]["line"]["publicCode"]
        dest = dep.get("destinationDisplay", {}).get("frontText", "")
        mode = dep["serviceJourney"]["line"].get("transportMode")
        mode_norm = (mode or "").lower()
        realtime = dep.get("realtime", False)

        # Simple mode icons (using unicode symbols)
        symbol = "🚊" if mode_norm == "tram" else "🚌"

        # --- Time calculations: scheduled vs updated ---
        mins_sched = None
        mins_updated = None

        try:
            # Scheduled (aimed) time
            aimed = dep.get("aimedArrivalTime")
            if aimed:
                t_aim = datetime.datetime.fromisoformat(
                    aimed.replace("Z", "+00:00")
                )
                mins_sched = int((t_aim - now_utc).total_seconds() / 60)
                mins_sched = max(mins_sched, 0)

            # Updated (expected) time
            expected = dep.get("expectedArrivalTime")
            if expected:
                t_exp = datetime.datetime.fromisoformat(
                    expected.replace("Z", "+00:00")
                )
                mins_updated = int((t_exp - now_utc).total_seconds() / 60)
                mins_updated = max(mins_updated, 0)

        except Exception as e:
            print("Time parse error:", e)
            mins_sched = None
            mins_updated = None

        # Fallback if only one is available
        if mins_updated is None and mins_sched is not None:
            mins_updated = mins_sched
        if mins_sched is None and mins_updated is not None:
            mins_sched = mins_updated

        dest_short = dest[:18]  # Slightly longer for grid layout

        # Grid columns: Mode | Line | Destination | Time
        draw.text((col_mode_x, y), symbol, fill=255, font=FONT_ICON)
        draw.text((col_line_x, y), line, fill=255, font=FONT)
        draw.text((col_dest_x, y), dest_short, fill=255, font=FONT)

        # --- Right-hand time with optional strikethrough ---
        if (
            realtime
            and mins_sched is not None
            and mins_updated is not None
            and mins_sched != mins_updated
        ):
            # There is a realtime update and the time changed
            sched_text = f"{mins_sched:>2}m"
            updated_text = f"{mins_updated:>2}m"

            # Draw scheduled time first
            sched_bbox = draw.textbbox((col_time_x, y), sched_text, font=FONT)
            draw.text((col_time_x, y), sched_text, fill=255, font=FONT)

            # Draw a strikethrough line across scheduled time
            mid_y = (sched_bbox[1] + sched_bbox[3]) // 2
            draw.line((sched_bbox[0], mid_y, sched_bbox[2], mid_y), fill=255, width=1)

            # Draw updated time just to the right
            updated_x = sched_bbox[2] + 4
            draw.text((updated_x, y), updated_text, fill=255, font=FONT)
        else:
            # No realtime change: just show the current (updated) minutes
            mins = mins_updated if mins_updated is not None else 0
            draw.text((col_time_x, y), f"{mins:>2}m", fill=255, font=FONT)

        y += 15

    device.display(image)


if __name__ == "__main__":
    # Prepare timezone and refresh timing
    try:
        timezone_str = config.get("settings", {}).get("timezone", "Europe/Oslo")
        tz = ZoneInfo(timezone_str)
    except Exception:
        tz = datetime.timezone.utc

    refresh_ms = config.get("settings", {}).get("refreshInterval", 30000)
    refresh_s = refresh_ms / 1000.0

    next_fetch = 0
    cached_deps = []
    cached_stop_infos = []

    try:
        while True:
            now = time.time()
            if now >= next_fetch:
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                cached_deps, cached_stop_infos = get_all_departures(tz, now_utc)
                next_fetch = now + refresh_s

            draw_board(cached_deps, cached_stop_infos, tz)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting")
