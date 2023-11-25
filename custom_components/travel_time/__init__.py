'''
Support for travel_time
Author        : dscao
Github        : https://github.com/dscao
Description   : 
Date          : 2023-11-23
LastEditors   : dscao
LastEditTime  : 2023-11-25
'''
"""    
Component to integrate with travel_time.

For more details about this component, please refer to
https://github.com/dscao/travel_time
"""
from async_timeout import timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, Config
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from urllib3.util.retry import Retry
from homeassistant.exceptions import ConfigEntryNotReady
import hashlib
import urllib.parse

import time
import datetime
import logging
import asyncio
import requests
import re
import json
from .helper import wgs84togcj02, wgs84_to_bd09

from homeassistant.const import (
    Platform,
    CONF_NAME,
    CONF_API_KEY,
    ATTR_GPS_ACCURACY,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    STATE_HOME,
    STATE_NOT_HOME,
    MAJOR_VERSION, 
    MINOR_VERSION,
)

from .const import (
    CONF_ORIGIN,
    CONF_DESTINATION,
    CONF_WAY,
    CONF_TACTICS,
    CONF_UPDATE_INTERVAL,
    CONF_PRIVATE_KEY,
    CONF_WEB_HOST,
    DOMAIN,
    COORDINATOR,
    UNDO_UPDATE_LISTENER,
)

TYPE_GEOFENCE = "Geofence"
__version__ = '2023.11.16'

_LOGGER = logging.getLogger(__name__)   
    
PLATFORMS = [Platform.SENSOR]

USER_AGENT = 'iphone OS 15.4.1'
API_URL_BAIDU = "https://api.map.baidu.com" 
API_URL_GAODE = "https://restapi.amap.com" 
API_URL_QQ = "https://apis.map.qq.com" 

WAY_BAIDU = ["/directionlite/v1/driving","/directionlite/v1/riding","/directionlite/v1/walking"]
WAY_GAODE = ["/v3/direction/driving","/v4/direction/bicycling","/v3/direction/walking"]
WAY_QQ = ["/ws/direction/v1/driving/","/ws/direction/v1/bicycling/","/ws/direction/v1/walking/","/ws/direction/v1/ebicycling/"]
TACTICS_BAIDU = [0,1,2,3,4,5]
TACTICS_GAODE = [0,13,4,2,1,5]
TACTICS_QQ = ["LEAST_TIME","AVOID_HIGHWAY","REAL_TRAFFIC","LEAST_TIME","LEAST_FEE","HIGHROAD_FIRST"]

TRAFFIC_STATUS = {
    0: "无路况",
    1: "畅通",
    2: "缓行",
    3: "拥堵",
    4: "非常拥堵"
}
        
async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """Set up configured travel_time."""
    # if (MAJOR_VERSION, MINOR_VERSION) < (2022, 4):
        # _LOGGER.error("Minimum supported Hass version 2022.4")
        # return False
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass, config_entry) -> bool:
    """Set up travel_time as config entry."""
    name = config_entry.data[CONF_NAME]
    webhost = config_entry.data[CONF_WEB_HOST]
    api_key = config_entry.data[CONF_API_KEY]
    private_key = config_entry.data.get(CONF_PRIVATE_KEY,"")
    _LOGGER.debug("private_key: %s", private_key)
    origin = config_entry.data[CONF_ORIGIN]
    destination = config_entry.data[CONF_DESTINATION]
    way = config_entry.options.get(CONF_WAY, "0")
    tactics = config_entry.options.get(CONF_TACTICS, "0")
    update_interval_seconds = config_entry.options.get(CONF_UPDATE_INTERVAL, 90)
    location_key = config_entry.unique_id 

    _LOGGER.debug("Using location_key: %s, update_interval_seconds: %s", location_key, update_interval_seconds)

    coordinator = travel_timeDataUpdateCoordinator(
        hass, webhost, api_key, private_key, name, origin, destination, way, tactics, location_key, update_interval_seconds
    )
    
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    undo_listener = config_entry.add_update_listener(update_listener)

    hass.data[DOMAIN][config_entry.entry_id] = {
        COORDINATOR: coordinator,
        UNDO_UPDATE_LISTENER: undo_listener,
    }

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, component)
        )

    return True

async def async_unload_entry(hass, config_entry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, component)
                for component in PLATFORMS
            ]
        )
    )

    hass.data[DOMAIN][config_entry.entry_id][UNDO_UPDATE_LISTENER]()

    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok


async def update_listener(hass, config_entry):
    """Update listener."""
    await hass.config_entries.async_reload(config_entry.entry_id)


class travel_timeDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching travel_time data API."""

    def __init__(self, hass, webhost, api_key, private_key, name, origin, destination, way, tactics, location_key, update_interval_seconds):
        """Initialize."""
        
        
        self.hass = hass
        self.location_key = location_key
        self.devicename = name
        self.webhost = webhost
        self.api_key = api_key
        self.private_key = private_key
        self.origin = origin
        self.destination = destination
        self.way = way
        self.tactics = tactics
        self._cood_old = []
        self._attrs = {}
        self.querytime = None
        self.distance = None
        self.duration = None
        self.traffic_condition = None
        
        update_interval = (
            datetime.timedelta(seconds=int(update_interval_seconds))
        )
        _LOGGER.debug("Data will be update every %s", update_interval)
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)


    def get_baidu_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        lng_o, lat_o = wgs84_to_bd09(lng_o, lat_o)
        lng_d, lat_d = wgs84_to_bd09(lng_d, lat_d)
        origin = str("{:.6f}".format(lat_o))+','+str("{:.6f}".format(lng_o))
        destination = str("{:.6f}".format(lat_d))+','+str("{:.6f}".format(lng_d))
        sn = ''
        timestamp = str(int(time.time()*1000))
        _LOGGER.debug("private_key: %s", private_key)
        if private_key: 
            params = WAY_BAIDU[int(way)]+'?ak='+api_key+'&tactics='+tactics+'&origin='+origin+'&destination='+destination+'&timestamp='+timestamp
            sn = self.baidu_sn(params, private_key)
            _LOGGER.debug("sn: %s", sn)
        url = API_URL_BAIDU+WAY_BAIDU[int(way)]+'?ak='+api_key+'&tactics='+tactics+'&origin='+origin+'&destination='+destination+'&timestamp='+timestamp+'&sn='+sn
        _LOGGER.debug(url)
        response = self.get_data(url)
        _LOGGER.debug(response)
        return response
        
    def get_gaode_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        lng_o, lat_o = wgs84togcj02(lng_o, lat_o)
        lng_d, lat_d = wgs84togcj02(lng_d, lat_d)
        origin = str("{:.6f}".format(lng_o))+','+str("{:.6f}".format(lat_o))
        destination = str("{:.6f}".format(lng_d))+','+str("{:.6f}".format(lat_d))
        sig = ''
        if private_key:
            params = {'key': api_key, 'destination': destination,'extensions': "all",'origin': origin, 'output': 'JSON', 'strategy': str(TACTICS_GAODE[int(tactics)])}
            sig = self.generate_signature(params, private_key)
        url = API_URL_GAODE+WAY_GAODE[int(way)]+'?origin='+origin+'&destination='+destination+'&strategy='+str(TACTICS_GAODE[int(tactics)])+'&output=JSON&extensions=all&key='+api_key+'&sig='+sig
        _LOGGER.debug(url)
        response = self.get_data(url)
        _LOGGER.debug(response)
        return response
        
    def get_qq_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        lng_o, lat_o = wgs84togcj02(lng_o, lat_o)
        lng_d, lat_d = wgs84togcj02(lng_d, lat_d)
        origin = str("{:.6f}".format(lat_o))+','+str("{:.6f}".format(lng_o))
        destination = str("{:.6f}".format(lat_d))+','+str("{:.6f}".format(lng_d))
        sk = ''
        if private_key:
            params = WAY_QQ[int(way)]+'?from='+origin+'&get_speed=1&key='+api_key+'&output=json&policy='+TACTICS_QQ[int(tactics)]+'&to='+destination
            sig = self.tencent_sk(params, private_key)
        url = API_URL_QQ+WAY_QQ[int(way)]+'?from='+origin+'&to='+destination+'&policy='+TACTICS_QQ[int(tactics)]+'&get_speed=1&output=json&key='+api_key+'&sig='+sig
        _LOGGER.debug(url)
        response = self.get_data(url)
        _LOGGER.debug(response)
        return response
        
    def get_data(self, url):
        json_text = requests.get(url)
        resdata = json_text.json()
        return resdata
        
    def generate_signature(self, params, private_key):
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_str = '&'.join([f'{key}={value}' for key, value in sorted_params])
        param_str += private_key
        signature = hashlib.md5(param_str.encode()).hexdigest()
        return signature
        
    def baidu_sn(self, params, private_key):
        param_str = urllib.parse.quote(params, safe="/:=&?#+!$,;'@()*[]")
        param_str += private_key
        signature = hashlib.md5(urllib.parse.quote_plus(param_str).encode()).hexdigest()
        return signature
        
    def tencent_sk(self, params, private_key):
        param_str = params + private_key
        signature = hashlib.md5(param_str.encode()).hexdigest()
        return signature
        
    def remove_tags(self, text):
        TAG_RE = re.compile(r'<[^>]+>')
        return TAG_RE.sub('', text)
        
    async def _async_update_data(self):
        """Update data via library."""
        if self.webhost == "baidu.com":
            manufacturer = "百度地图"
            device_model = "百度地图路线规划"
            sw_version = "1.0"
        elif self.webhost == "amap.com":
            manufacturer = "高德地图"
            device_model = "高德地图路径规划"
            sw_version = "1.0"        
        elif self.webhost == "qq.com":
            manufacturer = "腾讯地图"
            device_model = "腾讯地图路线规划"
            sw_version = "1.0"            
        else:
            _LOGGER.error("配置的平台不支持，请删除集成条目重新配置！")
            return
        
        origin_state = self.hass.states.get(self.origin)
        destination_state = self.hass.states.get(self.destination)
        if origin_state and destination_state:         
            origin_latitude = origin_state.attributes.get('latitude')
            origin_longitude = origin_state.attributes.get('longitude')
            destination_latitude = destination_state.attributes.get('latitude')
            destination_longitude = destination_state.attributes.get('longitude')         
            if self._cood_old != [origin_latitude, origin_longitude, destination_latitude, destination_longitude]:
                data = {}
                if self.webhost == "baidu.com":
                    if int(self.way) > 2:
                        self.way = "0"
                    try:
                        async with timeout(10): 
                            data = await self.hass.async_add_executor_job(self.get_baidu_directionlite, self.way, self.tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, self.api_key, self.private_key)
                    except Exception as error:
                        raise error
                    if data.get('status') == 0:
                        step = data['result']['routes'][0]['steps']
                        timecost = data['result']['routes'][0]['duration']
                        timecost = str(int(timecost)//60)
                        road_dict = {}
                        if self.way == '0':
                            for i in range(len(step)):
                                if step[i].get('traffic_condition'):
                                    status = step[i]['traffic_condition'][0]['status']
                                else:
                                    status = 0
                                if status in TRAFFIC_STATUS:
                                    traffic_status = TRAFFIC_STATUS[status]
                                else:
                                    traffic_status  = '未知'
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = traffic_status
                        else:
                            for i in range(len(step)):
                                if step[i].get('duration'):
                                    status = str(int(step[i]['duration'])//60)
                                else:
                                    status = "未知"
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = status
                        attr_dict = {}
                        for key,value in road_dict.items():
                            attr_dict[str(key)] = value
                        self._attrs = attr_dict
                        self.duration = timecost
                        self.distance = float(data['result']['routes'][0]['distance'])/1000                    
                        self.querytime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self._cood_old = [origin_latitude, origin_longitude, destination_latitude, destination_longitude]
                        if self.way == '0':
                            self.traffic_condition = TRAFFIC_STATUS[data['result']['routes'][0]['traffic_condition']]
                        else:
                            self.traffic_condition = "非驾车路线无路况"
                elif self.webhost == "amap.com":
                    if int(self.way) > 2:
                        self.way = "0"
                    try:
                        async with timeout(10): 
                            data = await self.hass.async_add_executor_job(self.get_gaode_directionlite, self.way, self.tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, self.api_key, self.private_key)
                    except Exception as error:
                        raise error
                    if data.get('status') == "1" or data.get("errcode")==0:
                        if self.way == '1':
                            step = data['data']['paths'][0]['steps']
                            timecost = data['data']['paths'][0]['duration']
                            self.distance = float(data['data']['paths'][0]['distance'])/1000
                        else:
                            step = data['route']['paths'][0]['steps']
                            timecost = data['route']['paths'][0]['duration']
                            self.distance = float(data['route']['paths'][0]['distance'])/1000
                        timecost = str(int(timecost)//60)
                        road_dict = {}
                        if self.way == '0':
                            for i in range(len(step)):
                                if step[i].get('tmcs'):
                                    status = step[i]['tmcs'][0]['status']
                                else:
                                    status = "未知"
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = status
                        else:
                            for i in range(len(step)):
                                if step[i].get('duration'):
                                    status = str(int(step[i]['duration'])//60)
                                else:
                                    status = "未知"
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = status
                        attr_dict = {}
                        for key,value in road_dict.items():
                            attr_dict[str(key)] = value
                        self._attrs = attr_dict
                        self.duration = timecost
                        self.querytime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self._cood_old = [origin_latitude, origin_longitude, destination_latitude, destination_longitude]
                        if self.way == '0':
                            self.traffic_condition = "属性中查看" #TRAFFIC_STATUS[data['route']['paths'][0].get('traffic_condition'), 0]
                        else:
                            self.traffic_condition = "非驾车路线无路况"
                elif self.webhost == "qq.com":
                    if int(self.way) > 3:
                        self.way = "0"
                    try:
                        async with timeout(10): 
                            data = await self.hass.async_add_executor_job(self.get_qq_directionlite, self.way, self.tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, self.api_key, self.private_key)
                    except Exception as error:
                        raise error
                    if data.get('status') == 0:
                        step = data['result']['routes'][0]['steps']
                        if self.way == '0':
                            speed = data['result']['routes'][0]['speed']
                        timecost = data['result']['routes'][0]['duration']
                        #timecost = str(int(timecost)//60)
                        road_dict = {}
                        if self.way == '0':
                            for i in range(len(step)):
                                if step[i].get('traffic_condition'):
                                    status = step[i]['traffic_condition'][0]['status']
                                else:
                                    status = 0
                                if status in TRAFFIC_STATUS:
                                    traffic_status = TRAFFIC_STATUS[status]
                                else:
                                    traffic_status  = '未知'
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = traffic_status
                        elif self.way == '3':
                            for i in range(len(step)):
                                if step[i].get('distance'):
                                    status = float(step[i]['distance'])/1000
                                else:
                                    status = '未知'                                
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = status
                        else:
                            for i in range(len(step)):
                                if step[i].get('duration'):
                                    status = str(int(step[i]['duration'])//60)
                                else:
                                    status = "未知"
                                road_dict[str(i) + ' - ' + self.remove_tags(step[i]['instruction'])] = status
                        attr_dict = {}
                        for key,value in road_dict.items():
                            attr_dict[str(key)] = value
                        self._attrs = attr_dict
                        self.duration = timecost
                        self.distance = float(data['result']['routes'][0]['distance'])/1000                    
                        self.querytime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self._cood_old = [origin_latitude, origin_longitude, destination_latitude, destination_longitude]
                        if self.way == '0':
                            self.traffic_condition = str(data['result']['routes'][0]['traffic_light_count']) + "个红绿灯"
                        else:
                            self.traffic_condition = "非驾车路线无路况"
                else:
                    _LOGGER.error("配置的平台不支持，请删除集成条目重新配置！")
                    return
                    
        if self.way == "0":
            sw_version = "驾车规划" + sw_version
        elif self.way == "1":
            sw_version = "骑行规划" + sw_version
        elif self.way == "2":
            sw_version = "步行规划" + sw_version
        elif self.way == "3":
            sw_version = "电动车规划" + sw_version

        return {"location_key":self.location_key,"devicename":self.devicename,"manufacturer":manufacturer,"device_model":device_model,"sw_version":sw_version,"querytime":self.querytime,"distance":self.distance,"duration":self.duration,"traffic_condition":self.traffic_condition,"attrs":self._attrs}

