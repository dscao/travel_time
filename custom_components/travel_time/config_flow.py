"""Adds config flow for travel_time."""
import logging
import asyncio
import json
import time, datetime
import requests
import re
import hashlib
import urllib.parse
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from collections import OrderedDict
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    CONF_ORIGIN,
    CONF_DESTINATION,
    CONF_TACTICS,
    CONF_WAY,
    CONF_UPDATE_INTERVAL,
    CONF_PRIVATE_KEY,
    CONF_WEB_HOST,
    DOMAIN,
)

import voluptuous as vol

USER_AGENT = 'iphone OS 15.4.1'
API_URL_BAIDU = "https://api.map.baidu.com" 
API_URL_GAODE = "https://restapi.amap.com" 
API_URL_QQ = "https://apis.map.qq.com" 

_LOGGER = logging.getLogger(__name__)

WEBHOST = {    
    "baidu.com": "百度地图",
    "amap.com": "高德地图",
    "qq.com": "腾讯地图"
}
WAY_BAIDU = ["/directionlite/v1/driving","/directionlite/v1/riding","/directionlite/v1/walking"]
WAY_GAODE = ["/v3/direction/driving","/v4/direction/bicycling","/v3/direction/walking"]
WAY_QQ = ["/ws/direction/v1/driving/","/ws/direction/v1/bicycling/","/ws/direction/v1/walking/","/ws/direction/v1/ebicycling/"]
TACTICS_BAIDU = [0,1,2,3,4,5]
TACTICS_GAODE = [0,13,4,2,1,5]
TACTICS_QQ = ["LEAST_TIME","AVOID_HIGHWAY","REAL_TRAFFIC","LEAST_TIME","LEAST_FEE","HIGHROAD_FIRST"]


@config_entries.HANDLERS.register(DOMAIN)
class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlow(config_entry)

    def __init__(self):
        """Initialize."""
        self._errors = {}
    
    def get_baidu_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        origin = str("{:.6f}".format(lat_o))+','+str("{:.6f}".format(lng_o))
        destination = str("{:.6f}".format(lat_d))+','+str("{:.6f}".format(lng_d))
        sn = ''
        timestamp = str(int(time.time()*1000))
        if private_key:            
            params = WAY_BAIDU[way]+'?ak='+api_key+'&origin='+origin+'&destination='+destination+'&tactics='+str(tactics)+'&timestamp='+timestamp
            sn = self.baidu_sn(params, private_key)
        url = API_URL_BAIDU+WAY_BAIDU[way]+'?ak='+api_key+'&origin='+origin+'&destination='+destination+'&tactics='+str(tactics)+'&timestamp='+timestamp+'&sn='+sn
        _LOGGER.debug(url)
        response = self.get_data(url)
        _LOGGER.debug(response)
        return response
        
    def get_gaode_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        origin = str("{:.6f}".format(lng_o))+','+str("{:.6f}".format(lat_o))
        destination = str("{:.6f}".format(lng_d))+','+str("{:.6f}".format(lat_d))
        sig = ''
        if private_key:
            params = {'key': api_key, 'destination': destination,'extensions': "all",'origin': origin, 'output': 'JSON', 'strategy': str(TACTICS_GAODE[int(tactics)])}
            sig = self.generate_signature(params, private_key)
        url = API_URL_GAODE+WAY_GAODE[way]+'?origin='+origin+'&destination='+destination+'&strategy='+str(TACTICS_GAODE[int(tactics)])+'&output=JSON&extensions=all&key='+api_key+'&sig='+sig
        _LOGGER.debug(url)
        response = self.get_data(url)
        _LOGGER.debug(response)
        return response
        
    def get_qq_directionlite(self, way, tactics, lat_o, lng_o, lat_d, lng_d, api_key, private_key):
        origin = str("{:.6f}".format(lat_o))+','+str("{:.6f}".format(lng_o))
        destination = str("{:.6f}".format(lat_d))+','+str("{:.6f}".format(lng_d))
        sk = ''
        if private_key:
            params = WAY_QQ[way]+'?from='+origin+'&get_speed=1&key='+api_key+'&output=json&policy='+TACTICS_QQ[tactics]+'&to='+destination
            sig = self.tencent_sk(params, private_key)
        url = API_URL_QQ+WAY_QQ[way]+'?from='+origin+'&to='+destination+'&policy='+TACTICS_QQ[tactics]+'&get_speed=1&output=json&key='+api_key+'&sig='+sig
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

    async def async_step_user(self, user_input={}):
        self._errors = {}
        if user_input is not None:
            # Check if entered host is already in HomeAssistant
            existing = await self._check_existing(user_input[CONF_NAME])
            if existing:
                return self.async_abort(reason="already_configured")

            # If it is not, continue with communication test
            webhost = user_input[CONF_WEB_HOST]
            origin_state = self.hass.states.get(user_input.get(CONF_ORIGIN))
            destination_state = self.hass.states.get(user_input.get(CONF_DESTINATION))
            origin_latitude = origin_state.attributes.get('latitude')
            origin_longitude = origin_state.attributes.get('longitude')
            destination_latitude = destination_state.attributes.get('latitude')
            destination_longitude = destination_state.attributes.get('longitude')
            api_key = user_input.get(CONF_API_KEY)
            private_key = user_input.get(CONF_PRIVATE_KEY)
            way = 0
            tactics = 0
            if webhost == "baidu.com":
                ret = await self.hass.async_add_executor_job(self.get_baidu_directionlite, way, tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, api_key, private_key)
            elif webhost == "amap.com":
                ret = await self.hass.async_add_executor_job(self.get_gaode_directionlite, way, tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, api_key, private_key)
            elif webhost == "qq.com":
                ret = await self.hass.async_add_executor_job(self.get_qq_directionlite, way, tactics, origin_latitude, origin_longitude, destination_latitude, destination_longitude, api_key, private_key)
            else:
                self._errors["base"] = "配置的平台不支持"
            _LOGGER.debug(ret)
            if (ret['status'] == 0 and (webhost == "baidu.com" or webhost == "qq.com")) or (ret['status'] == "1" and webhost == "amap.com"):
                await self.async_set_unique_id(f"travel_time-{user_input[CONF_WEB_HOST]}-{user_input[CONF_NAME]}".replace(".","_"))
                self._abort_if_unique_id_configured()
                _LOGGER.debug(user_input[CONF_NAME])
                _LOGGER.debug(user_input)
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
            else:
                self._errors["base"] = "communication"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def _show_config_form(self, user_input):

        # Defaults
        device_states = self.hass.states.async_all(['device_tracker', 'zone'])
        device_entities = []

        for state in device_states:
            if state.attributes.get('latitude') and state.attributes.get('longitude'):
                friendly_name = state.attributes.get('friendly_name')
                platform = state.attributes.get('platform')
                entity_id = state.entity_id
                value = f'{friendly_name}（{entity_id}）'
                device_entities.append(entity_id)
            
        device_name = "小汽车回家交通路况"
        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_NAME, default=device_name)] = str
        data_schema[vol.Required(CONF_WEB_HOST, default="")] = vol.All(str, vol.In(WEBHOST))
        data_schema[vol.Required(CONF_API_KEY ,default ="")] = str
        data_schema[vol.Optional(CONF_PRIVATE_KEY ,default ="")] = str
        data_schema[vol.Required(CONF_ORIGIN ,default ="")] = vol.All(str, vol.In(device_entities))
        data_schema[vol.Required(CONF_DESTINATION ,default ="")] = vol.All(str, vol.In(device_entities))
        
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=self._errors
        )

    async def async_step_import(self, user_input):
        """Import a config entry.

        Special type of import, we're not actually going to store any data.
        Instead, we're going to rely on the values that are in config file.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="configuration.yaml", data={})

    async def _check_existing(self, host):
        for entry in self._async_current_entries():
            if host == entry.data.get(CONF_NAME):
                return True

class OptionsFlow(config_entries.OptionsFlow):
    """Config flow options for travel_time."""

    def __init__(self, config_entry):
        """Initialize travel_time options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(CONF_UPDATE_INTERVAL, 60),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),                     
                    vol.Optional(
                        CONF_WAY, 
                        default=self.config_entry.options.get(CONF_WAY,"0")
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "0", "label": "驾车路线规划"},
                                {"value": "1", "label": "骑行路线规划"},
                                {"value": "2", "label": "步行路线规划"},
                                {"value": "3", "label": "电动车路线规划(仅支持腾讯地图)"}
                            ], 
                            multiple=False,translation_key="way"
                        )
                    ),
                    vol.Optional(
                        CONF_TACTICS, 
                        default=self.config_entry.options.get(CONF_TACTICS,"0")
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "5", "label": "大路优先"},
                                {"value": "4", "label": "花费最少"},
                                {"value": "3", "label": "最短距离"},
                                {"value": "2", "label": "躲避拥堵"},
                                {"value": "1", "label": "不走高速"},
                                {"value": "0", "label": "常规路线(时间最短)"}
                            ], 
                            multiple=False,translation_key="tactics"
                        )
                    )
                }
            )
        )

