"""
Integration with NWS severe weather warnings API
Forked from VERSION: 0.0.1 of https://github.com/mcaminiti/nws_warnings

API Documentation
---------------------------------------------------------
https://www.weather.gov/documentation/services-web-api
---------------------------------------------------------
"""
import asyncio
import logging
import time
from datetime import timedelta, datetime, timezone

import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    ATTR_ATTRIBUTION,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'nws_warnings'

NWS_API_ENDPOINT = 'https://api.weather.gov/alerts'

USER_AGENT = 'Home Assistant'

PARAM_POINT = 'point'
PARAM_START = 'start'
PARAM_END = 'end'
PARAM_STATUS = 'status'
PARAM_MESSAGE_TYPE = 'message_type'
PARAM_SEVERITY = 'severity'

VALID_MESSAGE_TYPE = [
    'alert',
    'update'
]
VALID_SEVERITY = [
    'unknown',
    'minor',
    'moderate',
    'severe',
    'extreme'
]

CONF_SEVERITY = 'severity'
CONF_MESSAGE_TYPE = 'message_type'
CONF_FORECAST_DAYS = 'forecast_days'
CONF_ZONE = 'zone'
CONF_LOCATION = 'location'

DEFAULT_MESSAGE_TYPE = [
    'alert',
    'update'
]
DEFAULT_SEVERITY = [
    'moderate',
    'severe',
    'extreme'
]
DEFAULT_ZONE = 'zone.home'
DEFAULT_NAME = 'NWS Warnings'

ATTR_UPDATES = 'updates'

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=5)

DEFAULT_ICON = 'mdi:alert'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_SEVERITY, default=DEFAULT_SEVERITY): vol.All(
        cv.ensure_list,
        [vol.In(VALID_SEVERITY)]
    ),
    vol.Optional(CONF_MESSAGE_TYPE, default=DEFAULT_MESSAGE_TYPE): vol.All(
        cv.ensure_list,
        [vol.In(VALID_MESSAGE_TYPE)]
    ),
    vol.Optional(CONF_FORECAST_DAYS): vol.All(
        cv.positive_int,
        vol.Range(min=1, max=5)
    ),
    vol.Exclusive(CONF_ZONE, "location"): cv.entity_id,
    vol.Exclusive(CONF_LOCATION, "location"): vol.Schema({
        vol.Required(CONF_LATITUDE): cv.latitude,
        vol.Required(CONF_LONGITUDE): cv.longitude
    }),
    vol.Optional(CONF_ICON, default=DEFAULT_ICON): cv.icon
})


def _get_headers():
    return {
        'User-Agent': USER_AGENT,
        'Accept': 'application/geo+json'
    }


def _get_query_params(severity, message_type, latitude, longitude):
    return {
        PARAM_MESSAGE_TYPE: message_type,
        PARAM_SEVERITY: severity,
        PARAM_POINT: "%s,%s" % (latitude, longitude)
    }


def _append_time_params(params, start, end):
    if start and end:
        params[PARAM_START] = start
        params[PARAM_END] = end

    return params


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the NWS sensor platform."""
    sensor = NWSWarningsEntity(hass, config)
    add_entities([sensor])
    return True


# pylint: disable=too-many-instance-attributes
class NWSWarningsEntity(Entity):
    """Sensor entity for NWS warnings"""

    def __init__(self, hass, config):
        self._hass = hass
        self._name = config[CONF_NAME]
        self._icon = config[CONF_ICON]
        self._severity = ','.join(config[CONF_SEVERITY])
        self._message_type = ','.join(config[CONF_MESSAGE_TYPE])
        self._zone = config.get(CONF_ZONE, None)
        self._location = config.get(CONF_LOCATION, None)
        self._forecast_days = config.get(CONF_FORECAST_DAYS, None)
        self._active_only = not self._forecast_days
        self._state = ''
        self._updates = []
        self._websession = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return {
            ATTR_UPDATES: self._updates,
            ATTR_ATTRIBUTION: "Data provided by NWS"
        }

    def _get_zone_lat_long(self):
        zone = self._hass.states.get(self._zone)
        if not zone:
            _LOGGER.error("Unable to retrieve zone %s",
                          self._zone)
            return [None, None]

        latitude = zone.attributes.get(ATTR_LATITUDE, None)
        longitude = zone.attributes.get(ATTR_LONGITUDE, None)
        if not latitude or not longitude:
            _LOGGER.error("Unable to retrieve latitude and longitude from %s",
                          self._zone)
            return [None, None]
        return [latitude, longitude]

    # pylint: disable=too-many-locals
    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Retrieve information from NWS api."""
        latitude = None
        longitude = None
        if self._location:
            latitude = self._location.get(CONF_LATITUDE, None)
            longitude = self._location.get(CONF_LONGITUDE, None)
        elif self._zone:
            [latitude, longitude] = self._get_zone_lat_long()

        if not latitude or not longitude:
            return False

        params = _get_query_params(
            self._severity,
            self._message_type,
            latitude,
            longitude
        )

        if not self._active_only:
            utc_offset = timedelta(
                seconds=-(time.altzone if time.localtime().tm_isdst else time.timezone))
            now = (datetime.now().replace(tzinfo=timezone(offset=utc_offset)) - timedelta(days=1))
            start = datetime(year=now.year, month=now.month,
                             day=now.day, hour=0, second=0,
                             tzinfo=timezone(offset=utc_offset))
            end = start + timedelta(days=self._forecast_days + 1)
            params = _append_time_params(
                params,
                start.isoformat(),
                end.isoformat()
            )

        url = NWS_API_ENDPOINT if not self._active_only else "%s/active" % NWS_API_ENDPOINT

        if self._websession is None:
            self._websession = async_create_clientsession(self._hass)

        try:

            with async_timeout.timeout(10):
                response = await self._websession.get(url, params=params, headers=_get_headers())

                if response.status != 200:
                    _LOGGER.warning("Error %d getting nws alerts.", response.status)
                    return False

                json = await response.json()

                self._state = None
                self._updates = {}
                for feature in json.get('features', []):
                    update = feature.get('properties', {}).get('headline', None)
                    sent = feature.get('properties', {}).get('sent', None)
                    if update and sent:
                        if not self._state:
                            self._state = update
                        self._updates[sent] = update

                self._state = self._state or ' '

                return True

        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Unable to update %s: %s",
                          self.entity_id,
                          str(err))
            return False
