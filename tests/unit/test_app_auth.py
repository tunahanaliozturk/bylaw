import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from bylaw.app.auth import REVIEW_PERMISSIONS, app_jwt

NOW = 1_700_000_000  # in the past, so only the expiry check needs turning off


def _key() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def test_the_app_jwt_is_rs256_backdated_a_minute_and_short_lived() -> None:
    private, public = _key()

    token = app_jwt("Iv23client", private, now=NOW)

    claims = jwt.decode(token, public, algorithms=["RS256"], options={"verify_exp": False})
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    assert claims == {"iss": "Iv23client", "iat": NOW - 60, "exp": NOW + 540}


def test_a_review_token_can_read_code_and_issues_and_write_only_to_pull_requests() -> None:
    assert REVIEW_PERMISSIONS == {
        "contents": "read",
        "issues": "read",
        "metadata": "read",
        "pull_requests": "write",
    }
