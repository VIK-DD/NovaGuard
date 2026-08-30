"""Dashboard token encryption: the key derivation, and migrating between keys.

Two separate concerns live here. One is that a token written under an older
key stays readable, so changing keys does not log the whole estate out at
once. The other is the derivation itself: it used to be a single round of
SHA-256, which is not a key-derivation function - it is fast by design, and
fast is exactly wrong for a value an operator might set to a passphrase
rather than to 32 random bytes.
"""

import time
import unittest
from unittest import mock

from core import web_storage


@unittest.skipIf(web_storage.Fernet is None, "cryptography is not installed")
class KeyDerivationTests(unittest.TestCase):
    def test_the_derivation_is_scrypt_not_a_bare_hash(self):
        # Same secret, the two derivations, and they must not agree - the
        # cheapest way to state "the fast one is no longer what we use".
        secret = "dedicated-key-2026-xxxxxxxxxxxxxxxx"
        current = web_storage._cipher_from_secret(secret)
        old = web_storage._cipher_from_secret(secret, legacy=True)
        token = current.encrypt(b"access-token")
        with self.assertRaises(web_storage.InvalidToken):
            old.decrypt(token)

    def test_the_derivation_actually_costs_something(self):
        # Not a benchmark - a floor. A single SHA-256 lands in microseconds,
        # so anything in this range proves a work factor is being applied.
        # Generous enough not to flake on a loaded CI runner.
        started = time.perf_counter()
        web_storage._cipher_from_secret("a-passphrase-someone-might-choose")
        elapsed = time.perf_counter() - started
        self.assertGreater(elapsed, 0.002, "derivation is too cheap to be a KDF")

    def test_the_same_secret_always_derives_the_same_key(self):
        # The salt is fixed on purpose: this key must be derivable from the
        # environment alone at import, with no stored state to consult.
        secret = "stable-secret-2026-xxxxxxxxxxxxxxxx"
        first = web_storage._cipher_from_secret(secret)
        second = web_storage._cipher_from_secret(secret)
        self.assertEqual(second.decrypt(first.encrypt(b"token")), b"token")

    def test_different_secrets_derive_different_keys(self):
        first = web_storage._cipher_from_secret("secret-one-2026-xxxxxxxxxxxxxxxxxx")
        second = web_storage._cipher_from_secret("secret-two-2026-xxxxxxxxxxxxxxxxxx")
        with self.assertRaises(web_storage.InvalidToken):
            second.decrypt(first.encrypt(b"token"))

    def test_no_secret_means_no_cipher(self):
        self.assertIsNone(web_storage._cipher_from_secret(""))
        self.assertIsNone(web_storage._cipher_from_secret(None))


@unittest.skipIf(web_storage.Fernet is None, "cryptography is not installed")
class WebTokenEncryptionTests(unittest.TestCase):
    def test_dedicated_key_encrypts_new_tokens(self):
        dedicated = web_storage._cipher_from_secret("dedicated-key-2026-xxxxxxxxxxxxxxxx")
        legacy = web_storage._cipher_from_secret("discord-secret")

        with (
            mock.patch.object(web_storage, "_CIPHER", dedicated),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", (legacy,)),
        ):
            encrypted = web_storage._encrypt_token("access-token")

        self.assertEqual(
            dedicated.decrypt(encrypted[len(web_storage.TOKEN_PREFIX):].encode()).decode(),
            "access-token",
        )
        with self.assertRaises(web_storage.InvalidToken):
            legacy.decrypt(encrypted[len(web_storage.TOKEN_PREFIX):].encode())

    def test_legacy_client_secret_rows_remain_readable(self):
        dedicated = web_storage._cipher_from_secret("dedicated-key-2026-xxxxxxxxxxxxxxxx")
        legacy = web_storage._cipher_from_secret("discord-secret")
        encrypted = web_storage.TOKEN_PREFIX + legacy.encrypt(b"old-access-token").decode()

        with (
            mock.patch.object(web_storage, "_CIPHER", dedicated),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", (legacy,)),
        ):
            self.assertEqual(web_storage._decrypt_token(encrypted), "old-access-token")

    def test_rows_written_by_the_pre_scrypt_derivation_still_read(self):
        # The migration that matters for existing installs: same secret, older
        # derivation. Nobody should be logged out by this upgrade.
        secret = "dedicated-key-2026-xxxxxxxxxxxxxxxx"
        current = web_storage._cipher_from_secret(secret)
        old = web_storage._cipher_from_secret(secret, legacy=True)
        encrypted = web_storage.TOKEN_PREFIX + old.encrypt(b"pre-upgrade-token").decode()

        with (
            mock.patch.object(web_storage, "_CIPHER", current),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", (old,)),
        ):
            self.assertEqual(web_storage._decrypt_token(encrypted), "pre-upgrade-token")

    def test_a_reread_row_is_rewritten_under_the_current_key(self):
        # How the estate migrates: read with the old key, write back with the
        # new one, so the fallback stops being load-bearing on its own.
        secret = "dedicated-key-2026-xxxxxxxxxxxxxxxx"
        current = web_storage._cipher_from_secret(secret)
        old = web_storage._cipher_from_secret(secret, legacy=True)
        encrypted = web_storage.TOKEN_PREFIX + old.encrypt(b"pre-upgrade-token").decode()

        with (
            mock.patch.object(web_storage, "_CIPHER", current),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", (old,)),
        ):
            plaintext = web_storage._decrypt_token(encrypted)
            rewritten = web_storage._encrypt_token(plaintext)

        body = rewritten[len(web_storage.TOKEN_PREFIX):].encode()
        self.assertEqual(current.decrypt(body), b"pre-upgrade-token")
        with self.assertRaises(web_storage.InvalidToken):
            old.decrypt(body)

    def test_unknown_key_fails_closed(self):
        primary = web_storage._cipher_from_secret("primary-key-2026-xxxxxxxxxxxxxxxxxxx")
        unknown = web_storage._cipher_from_secret("unknown-key-2026-xxxxxxxxxxxxxxxxxxx")
        encrypted = web_storage.TOKEN_PREFIX + unknown.encrypt(b"token").decode()

        with (
            mock.patch.object(web_storage, "_CIPHER", primary),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", ()),
        ):
            self.assertIsNone(web_storage._decrypt_token(encrypted))


if __name__ == "__main__":
    unittest.main()
