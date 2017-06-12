#!/usr/bin/python
#
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import certifi
import json
import logging
import urllib3
from oauth2client.service_account import ServiceAccountCredentials

# Service management service
SERVICE_MGMT_ROLLOUTS_URL_TEMPLATE = (
    "https://servicemanagement.googleapis.com"
    "/v1/services/{}/rollouts?pageToken={}")

_GOOGLE_API_SCOPE = (
    "https://www.googleapis.com/auth/service.management.readonly")

# Metadata service path
_METADATA_PATH = "/computeMetadata/v1/instance"
_METADATA_SERVICE_NAME = "endpoints-service-name"
_METADATA_SERVICE_CONFIG_ID = "endpoints-service-config-id"

class FetchError(Exception):
    """Error class for fetching and validation errors."""
    def __init__(self, code, message):
        self.code = code
        self.message = message
    def __str__(self):
        return self.message

def fetch_service_name(metadata):
    """Fetch service name from metadata URL."""
    url = metadata + _METADATA_PATH + "/attributes/" + _METADATA_SERVICE_NAME
    headers = {"Metadata-Flavor": "Google"}
    client = urllib3.PoolManager(ca_certs=certifi.where())
    try:
        response = client.request("GET", url, headers=headers)
    except:
        raise FetchError(1,
            "Failed to fetch service name from the metadata server: " + url)
    status_code = response.status

    if status_code != 200:
        message_template = "Fetching service name failed (url {}, status code {})"
        raise FetchError(1, message_template.format(url, status_code))

    name = response.data
    logging.info("Service name: " + name)
    return name


def fetch_service_config_id(metadata):
    """Fetch service config ID from metadata URL."""
    url = metadata + _METADATA_PATH + "/attributes/" + _METADATA_SERVICE_CONFIG_ID
    headers = {"Metadata-Flavor": "Google"}
    client = urllib3.PoolManager(ca_certs=certifi.where())
    try:
        response = client.request("GET", url, headers=headers)
        if response.status != 200:
            message_template = "Fetching service config ID failed (url {}, status code {})"
            raise FetchError(1, message_template.format(url, response.status))
    except:
        url = metadata + _METADATA_PATH + "/attributes/endpoints-service-version"
        try:
            response = client.request("GET", url, headers=headers)
        except:
            raise FetchError(1,
                    "Failed to fetch service config ID from the metadata server: " + url)
        if response.status != 200:
            message_template = "Fetching service config ID failed (url {}, status code {})"
            raise FetchError(1, message_template.format(url, response.status))

    version = response.data
    logging.info("Service config ID:" + version)
    return version


def make_access_token(secret_token_json):
    """Construct an access token from service account token."""
    logging.info("Constructing an access token with scope " + _GOOGLE_API_SCOPE)
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        secret_token_json,
        scopes=[_GOOGLE_API_SCOPE])
    logging.info("Service account email: " + credentials.service_account_email)
    token = credentials.get_access_token().access_token
    return token


def fetch_access_token(metadata):
    """Fetch access token from metadata URL."""
    access_token_url = metadata + _METADATA_PATH + "/service-accounts/default/token"
    headers = {"Metadata-Flavor": "Google"}
    client = urllib3.PoolManager(ca_certs=certifi.where())
    try:
        response = client.request("GET", access_token_url, headers=headers)
    except:
        raise FetchError(1,
            "Failed to fetch access token from the metadata server: " + access_token_url)
    status_code = response.status

    if status_code != 200:
        message_template = "Fetching access token failed (url {}, status code {})"
        raise FetchError(1, message_template.format(access_token_url, status_code))

    token = json.loads(response.data)["access_token"]
    return token

def fetch_latest_rollout(service_name, access_token):
    """Fetch rollouts"""
    if access_token is None:
        headers = {}
    else:
        headers = {"Authorization": "Bearer {}".format(access_token)}

    client = urllib3.PoolManager(ca_certs=certifi.where())

    page_token = ""
    while True:
        service_mgmt_url = SERVICE_MGMT_ROLLOUTS_URL_TEMPLATE.format(
              service_name, page_token)

        try:
            response = client.request("GET", service_mgmt_url, headers=headers)
        except:
            raise FetchError(1, "Failed to fetch service config")

        status_code = response.status
        if status_code != 200:
            message_template = ("Fetching rollouts failed "\
                                "(status code {}, reason {}, url {})")
            raise FetchError(1, message_template.format(status_code,
                                                        response.reason,
                                                        service_mgmt_url))

        rollouts = json.loads(response.data)
        if rollouts["rollouts"] is None:
            message_template = ("Invalid rollouts response (url {}, data {})")
            raise FetchError(1, message_template.format(service_mgmt_url,
                                                        response.data))

        # Find first successful rollous
        for rollout in rollouts["rollouts"]:
            if rollout["status"] is not None and \
              rollout["status"] == "SUCCESS" and \
              rollout["trafficPercentStrategy"] is not None and \
              rollout["trafficPercentStrategy"]["percentages"] is not None:
                return rollout["trafficPercentStrategy"]["percentages"]

        # Stop fetching next page when nextPageToken is not defined
        if rollouts["nextPageToken"] is None:
            break
        
        # fetching next page
        page_token = rollouts["nextPageToken"]

    # No valid rollouts
    message_template = ("Fetching rollouts failed "\
                        "(status code {}, reason {}, url {})")
    raise FetchError(1, message_template.format(status_code, response.reason,
                                           service_mgmt_url))

def fetch_service_json(service_mgmt_url, access_token):
    """Fetch service config."""
    if access_token is None:
        headers = {}
    else:
        headers = {"Authorization": "Bearer {}".format(access_token)}

    client = urllib3.PoolManager(ca_certs=certifi.where())
    try:
        response = client.request("GET", service_mgmt_url, headers=headers)
    except:
        raise FetchError(1, "Failed to fetch service config")
    status_code = response.status

    if status_code != 200:
        message_template = "Fetching service config failed (status code {}, reason {}, url {})"
        raise FetchError(1, message_template.format(status_code, response.reason, service_mgmt_url))

    service_config = json.loads(response.data)
    return service_config


def validate_service_config(service_config, expected_service_name,
                            expected_service_version):
    """Validate service config."""
    service_name = service_config.get("name", None)

    if not service_name:
        raise FetchError(2, "No service name in the service config")

    if service_name != expected_service_name:
        message_template = "Unexpected service name in service config: {}"
        raise FetchError(2, message_template.format(service_name))

    service_version = service_config.get("id", None)

    if not service_version:
        raise FetchError(2, "No service config ID in the service config")

    if service_version != expected_service_version:
        message_template = "Unexpected service config ID in service config: {}"
        raise FetchError(2, message_template.format(service_version))

    # WARNING: sandbox migration workaround
    control = service_config.get("control", None)

    if not control:
        raise FetchError(2, "No control section in the service config")

    environment = control.get("environment", None)

    if not environment:
        raise FetchError(2, "Missing control environment")

    if environment == "endpoints-servicecontrol.sandbox.googleapis.com":
        logging.warning("Replacing sandbox control environment in the service config")
        service_config["control"]["environment"] = (
            "servicecontrol.googleapis.com")
