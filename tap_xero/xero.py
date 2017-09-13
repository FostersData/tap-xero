import requests
from os.path import join
import re
from datetime import datetime, date, time
import xero.utils
from singer.utils import strftime
import json
import six
from .credentials import build_oauth
import decimal
import pytz

BASE_URL = "https://api.xero.com/api.xro/2.0"


def _json_load_object_hook(_dict):
    """Hook for json.parse(...) to parse Xero date formats."""
    # This was taken from the pyxero library and modified
    # to format the dates according to RFC3339
    for key, value in _dict.items():
        if isinstance(value, six.string_types):
            value = xero.utils.parse_date(value)
            if value:
                if type(value) == date:
                    value = datetime.combine(value, time.min)
                value = value.replace(tzinfo=pytz.UTC)
                _dict[key] = strftime(value)
    return _dict


class XeroClient(object):
    def __init__(self, config):
        self.session = requests.Session()
        self.oauth = build_oauth(config)
        self.user_agent = config.get("user_agent")
        self._datetime_pattern = re.compile(r"\/Date\((\d+)\)\/")

    def _format_since(self, since):
        if isinstance(since, datetime):
            return since.strftime('%a, %d %b %Y %H:%M:%S GMT')
        return '"{}"'.format(since)

    def filter(self, tap_stream_id, *, since=None, **params):
        xero_resource_name = tap_stream_id.title().replace("_", "")
        url = join(BASE_URL, xero_resource_name)
        headers = {"Accept": "application/json"}
        if self.user_agent:
            headers["User-Agent"] = user_agent
        if since:
            headers["If-Modified-Since"] = self._format_since(since)
        request = requests.Request("GET", url, auth=self.oauth,
                                   headers=headers, params=params)
        response = self.session.send(request.prepare())
        response.raise_for_status()
        response_meta = json.loads(response.text,
                                   object_hook=_json_load_object_hook,
                                   parse_float=decimal.Decimal)
        response_body = response_meta.pop(xero_resource_name)
        return response_body
