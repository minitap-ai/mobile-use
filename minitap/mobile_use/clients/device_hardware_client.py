from urllib.parse import urljoin

from minitap.mobile_use.utils.requests_utils import get_session_with_curl_logging


class DeviceHardwareClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = get_session_with_curl_logging()

    def get(self, path: str, **kwargs):
        url = urljoin(self.base_url, f"/api/{path.lstrip('/')}")
        return self.session.get(url, **kwargs)

    def get_rich_hierarchy(self) -> list[dict]:
        return self.get("last-view-hierarchy").json().get("children", [])

    def post(self, path: str, **kwargs):
        url = urljoin(self.base_url, f"/api/{path.lstrip('/')}")
        return self.session.post(url, **kwargs)


def get_client(base_url: str | None = None):
    if not base_url:
        base_url = "http://localhost:9999"
    return DeviceHardwareClient(base_url)
