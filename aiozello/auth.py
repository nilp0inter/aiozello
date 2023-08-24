import time

import jwt


def generate_token(issuer, private_key, expiration=3600, current_time=lambda: int(time.time())):
    payload = {
        "iss": issuer,
        "exp": current_time() + expiration,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


class LocalTokenManager:
    def __init__(self, issuer, private_key_path, expiration=3600, current_time=lambda: int(time.time())):
        self.issuer = issuer
        with open(private_key_path, "r") as f:
            self.private_key = f.read()
        self.expiration = expiration
        self.current_time = current_time

    def issue(self):
        return generate_token(self.issuer, self.private_key, expiration=self.expiration, current_time=self.current_time)
