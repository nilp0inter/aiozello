import tempfile

import jwt
import cryptography

from aiozello.auth import LocalTokenManager, get_system_current_time


def test_LocalTokenManager_happy_path():
    with (
        tempfile.NamedTemporaryFile(suffix=".key") as private_key_file,
        tempfile.NamedTemporaryFile(suffix=".pem") as public_key_file,
    ):
        # 1. Create a pair of RSA private/public keys
        private_key = (
            cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
        )
        private_key_pem = private_key.private_bytes(
            encoding=cryptography.hazmat.primitives.serialization.Encoding.PEM,
            format=cryptography.hazmat.primitives.serialization.PrivateFormat.PKCS8,
            encryption_algorithm=cryptography.hazmat.primitives.serialization.NoEncryption(),
        )
        public_key = private_key.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=cryptography.hazmat.primitives.serialization.Encoding.PEM,
            format=cryptography.hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # 2. Store them in temporary files
        private_key_file.write(private_key_pem)
        private_key_file.flush()

        public_key_file.write(public_key_pem)
        public_key_file.flush()

        # 3. Create a LocalTokenManager instance
        issuer = "foobar"
        current_time = get_system_current_time()
        expiration = 42

        ltm = LocalTokenManager(
            issuer=issuer,
            private_key_path=private_key_file.name,
            expiration=expiration,
            get_current_time=lambda: current_time,
        )

        # 4. Issue a token
        token = ltm.issue()

        # 5. Verify that the returned token is valid using jwt.decode()
        try:
            decoded_token = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
            )
        except Exception as e:
            raise AssertionError("Failed to decode the token") from e
        else:
            assert decoded_token["iss"] == issuer
            assert decoded_token["exp"] == current_time + expiration
