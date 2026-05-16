"""Sync HTTP client for an internal API. To be refactored to async."""
import requests


class APIClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_user(self, user_id: int) -> dict:
        resp = requests.get(
            f"{self.base_url}/users/{user_id}", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def create_user(self, name: str, email: str) -> dict:
        resp = requests.post(
            f"{self.base_url}/users",
            json={"name": name, "email": email},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def list_users(self, page: int = 1) -> list[dict]:
        resp = requests.get(
            f"{self.base_url}/users",
            params={"page": page},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["users"]
