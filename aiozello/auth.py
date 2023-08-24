import time
from typing import Callable

import jwt


def generate_token(
    issuer: str,
    private_key: str,
    expiration: int,
    get_current_time: Callable[[], int],
):
    """A pure function that generates a JWT token."""
    payload = {
        "iss": issuer,
        "exp": get_current_time() + expiration,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def get_current_time() -> int:
    """An effectful function that returns the current time."""
    return int(time.time())


def read_private_key(path: str) -> str:
    """An effectful function that reads a private key from a file."""
    with open(path, "r") as f:
        return f.read()


class LocalTokenManager:
    """A class that generates a JWT token from a local private key."""

    def __init__(
        self,
        issuer: str,
        private_key_path: str,
        read_private_key: Callable[[str], str] = read_private_key,
        expiration: int = 3600,
        get_current_time: Callable[[], int] = get_current_time,
    ):
        self.issuer = issuer
        self.private_key = read_private_key(private_key_path)
        self.expiration = expiration
        self.get_current_time = get_current_time

    def issue(self):
        return generate_token(
            self.issuer,
            self.private_key,
            expiration=self.expiration,
            get_current_time=self.get_current_time,
        )
