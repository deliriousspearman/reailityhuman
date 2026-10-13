"""Password hashing for cloud-init (SHA-512 crypt, written out since Python 3.13 dropped crypt)."""

import secrets
import string
import sys
import warnings

import pytest

from app.cloudinit import hash_password, sha512_crypt


def test_sha512_crypt_matches_the_specification():
    # Test vectors from https://www.akkadia.org/drepper/SHA-crypt.txt
    assert sha512_crypt("Hello world!", "saltstring") == (
        "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"
    )
    assert sha512_crypt("Hello world!", "saltstringsaltstring", rounds=10000) == (
        "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTBmSK6H9qs/y3RnOaw5v."
    )


@pytest.mark.skipif(sys.version_info >= (3, 13), reason="the crypt module is gone")
def test_sha512_crypt_matches_the_system_crypt():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import crypt
    for length in [0, 1, 8, 16, 63, 64, 65, 127, 128, 200]:
        password = "".join(secrets.choice(string.printable) for _ in range(length))
        salt = crypt.mksalt(crypt.METHOD_SHA512)
        assert sha512_crypt(password, salt.removeprefix("$6$")) == crypt.crypt(password, salt)


def test_hash_password_salts_each_hash():
    a, b = hash_password("correct horse 9"), hash_password("correct horse 9")
    assert a.startswith("$6$") and a != b
