import time
from typing import Callable

import jwt


def generate_token(
    issuer: str,
    private_key: str,
    current_time: int,
    expiration: int,
):
    """A pure function that generates a JWT token."""
    payload = {
        "iss": issuer,
        "exp": current_time + expiration,
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
        get_current_time: Callable[[], int] = get_current_time,
        expiration: int = 3600,
    ):
        self.issuer = issuer
        self.private_key = read_private_key(private_key_path)
        self.get_current_time = get_current_time
        self.expiration = expiration

    def issue(self):
        return generate_token(
            self.issuer,
            self.private_key,
            self.get_current_time(),
            self.expiration,
        )
