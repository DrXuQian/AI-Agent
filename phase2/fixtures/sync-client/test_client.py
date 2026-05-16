"""Tests for the sync API client. Uses unittest.mock to fake requests."""
import unittest
from unittest.mock import MagicMock, patch

from client import APIClient


class TestAPIClient(unittest.TestCase):
    @patch("client.requests.get")
    def test_get_user(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 1, "name": "Alice"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = APIClient("http://api.test")
        user = client.get_user(1)

        self.assertEqual(user["id"], 1)
        mock_get.assert_called_once_with(
            "http://api.test/users/1", timeout=10.0
        )

    @patch("client.requests.post")
    def test_create_user(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 42, "name": "Bob", "email": "bob@x.com"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        client = APIClient("http://api.test")
        user = client.create_user("Bob", "bob@x.com")

        self.assertEqual(user["id"], 42)

    @patch("client.requests.get")
    def test_list_users(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"users": [{"name": "A"}, {"name": "B"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        client = APIClient("http://api.test")
        users = client.list_users(page=2)

        self.assertEqual(len(users), 2)


if __name__ == "__main__":
    unittest.main()
