"""Entry point that uses the sync client."""
import sys

from client import APIClient


def main(base_url: str) -> int:
    client = APIClient(base_url)
    users = client.list_users(page=1)
    print(f"Found {len(users)} users on page 1")
    for u in users[:5]:
        print(f"  - {u['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"))
