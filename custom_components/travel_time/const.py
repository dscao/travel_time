
"""Constants for travel_time."""
DOMAIN = "travel_time"

REQUIRED_FILES = [
    "const.py",
    "manifest.json",
    "sensor.py",
    "config_flow.py",
    "translations/en.json",
    "translations/zh-Hans.json",
]
VERSION = "2023.11.25"
ISSUE_URL = "https://github.com/dscao/travel_time/issues"

STARTUP = """
-------------------------------------------------------------------
{name}
Version: {version}
This is a custom component
If you have any issues with this you need to open an issue here:
{issueurl}
-------------------------------------------------------------------
"""

from homeassistant.const import (
    ATTR_DEVICE_CLASS,
)

ATTR_ICON = "icon"
ATTR_LABEL = "label"
MANUFACTURER = "lab.baidu.com."
NAME = "交通路况"
CONF_WEB_HOST = "webhost"
CONF_PRIVATE_KEY = "private_key"
CONF_ORIGIN = "origin"
CONF_DESTINATION = "destination"
CONF_WAY = "way"
CONF_TACTICS= "tactics"
CONF_ATTR_SHOW = "attr_show"
CONF_UPDATE_INTERVAL = "update_interval_seconds"


COORDINATOR = "coordinator"
UNDO_UPDATE_LISTENER = "undo_update_listener"

SENSOR_TYPES = {
    "distance": {
        "icon": "mdi:clock-time-eight",
        "label": "里程",
        "name": "distance",
        "unit_of_measurement": "公里",
    },
    "duration": {
        "icon": "mdi:clock-time-eight",
        "label": "时长",
        "name": "duration",
        "unit_of_measurement": "分钟",
    },
    "traffic_condition": {
        "icon": "mdi:clock-time-eight",
        "label": "路况",
        "name": "traffic_condition",
    },
}