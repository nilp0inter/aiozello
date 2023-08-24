from typing import Callable
import time

import jwt

from aiozello.error import TokenGenerationError


def generate_token_payload(
    issuer: str,
    current_time: int,
    expiration: int,
):
    return {
        "iss": issuer,
        "exp": current_time + expiration,
    }


def generate_token(
    issuer: str,
    private_key: str,
    current_time: int,
    expiration: int,
):
    payload = generate_token_payload(issuer, current_time, expiration)

    try:
        return jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as e:
        raise TokenGenerationError("Failed to generate token") from e


def get_system_current_time() -> int:
    return int(time.time())


def read_private_key_from_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


class LocalTokenManager:
    """A class that generates a JWT token from private key stored in a local file."""

    def __init__(
        self,
        issuer: str,
        private_key_path: str,
        get_private_key: Callable[[str], str] = read_private_key_from_file,
        get_current_time: Callable[[], int] = get_system_current_time,
        expiration: int = 3600,
    ):
        self.issuer = issuer
        self.private_key = get_private_key(private_key_path)
        self.get_current_time = get_current_time
        self.expiration = expiration

    def issue(self):
        return generate_token(
            self.issuer,
            self.private_key,
            self.get_current_time(),
            self.expiration,
        )
