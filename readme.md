# Departure Board

Real-time Norwegian public transport departures using [Entur's API](https://developer.entur.org/). Built for a physical SSD1322 256x64 OLED display powered by a Raspberry Pi Zero 2 W, with support for a web interface that can be embedded in Home Assistant or any browser.

## Features

- Real-time departures for multiple stops (trams, buses, trains, ferries, airports etc.)
- Delay detection with visual indicators
- Clean, minimalist display design
- Web interface for browsers and iFrames
- Hardware OLED support for physical displays

## Quick Start

### Web Interface

Perfect for testing API or embedding in dashboards like Home Assistant.

```bash
# Configure your stops
cp config/config.template.json config/config.json

# Start the web server
cd web && python3 -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

### OLED Display

This will require soldering, wiring knowledge and is not plug and play.

For physical hardware setup, see the [OLED Setup Guide](docs/oled-setup.md).

Quick version:

```bash
# Enable SPI on Raspberry Pi
sudo raspi-config  # Interface Options → SPI → Yes

# Install dependencies
python3 -m venv oled-env
source oled-env/bin/activate
pip install requests Pillow luma.oled luma.core smbus2

# Run the display
python3 oled.py
```

### Development Mode

Test OLED graphics on your development machine using the emulator.

```bash
python3 -m venv oled-env
source oled-env/bin/activate
pip install requests Pillow luma.emulator
python3 oled.py
```

## Configuration

Copy the template and edit config/config.json:

```bash
cp config/config.template.json config/config.json
```

Basic configuration:

```json
{
  "stops": [
    {
      "id": "NSR:StopPlace:12345",
      "name": "StopName",
      "type": "tram",
      "description": "Main tram stop"
    }
  ],
  "api": {
    "clientName": "your-client-name",
    "timeout": 10
  },
  "settings": {
    "numberOfDepartures": 3,
    "refreshInterval": 30000,
    "timezone": "Europe/Oslo"
  },
  "display": {
    "maxRows": 3,
    "showRealtime": true,
    "showDelayIndicator": true
  }
}
```

See [config.template.json](config/config.template.json) for all available options and descriptions.

### Finding Stop IDs

1. Visit [Entur's stop place search](https://stoppested.entur.org/)
2. Search for your stop
3. Copy the `NSR:StopPlace` ID from the URL or stop details

## Hardware

- Display: SSD1322 256x64 OLED (grayscale)
- Computer: Raspberry Pi Zero 2 W (or any Pi with GPIO)
- Interface: 4-wire SPI

For complete hardware setup, wiring diagrams, and troubleshooting, see:

- [OLED Setup Guide](docs/oled-setup.md) - Hardware preparation and software installation
- [Wiring Guide](docs/wiring.md) - Pin connections and SPI configuration

## Integration

### Home Assistant

Add to your dashboard configuration:

```yaml
type: iframe
url: http://<raspberry-pi-ip>:8080
aspect_ratio: 100%
```

### Systemd Service

To run the OLED display on boot, create `/etc/systemd/system/departure-board.service`:

```ini
[Unit]
Description=Departure Board OLED Display
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/departure-board
ExecStart=/home/pi/departure-board/oled-env/bin/python3 /home/pi/departure-board/oled.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable departure-board
sudo systemctl start departure-board
```

## Dependencies

- Python 3.10+
- Python packages:
  - `requests` - API calls
  - `Pillow` - Image rendering
  - `luma.oled` + `luma.core` - OLED display driver (hardware)
  - `luma.emulator` - Display emulator (development)
  - `smbus2` - I²C support (hardware)
