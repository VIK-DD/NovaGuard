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


@unittest.skipIf(web_storage.Fernet is None, "cryptography is not installed")
class InstallSaltTests(unittest.TestCase):
    """The salt is this install's, not every install's."""

    def test_the_salt_is_generated_once_and_then_reused(self):
        first = web_storage._read_or_create_install_salt()
        second = web_storage._read_or_create_install_salt()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_the_stored_salt_is_not_the_shipped_constant(self):
        # A constant compiled into the module means two installs sharing a
        # WEB_TOKEN_KEY derive the same key, and precomputing against a weak
        # one is worth doing once for everybody rather than once per install.
        self.assertNotEqual(web_storage._read_or_create_install_salt(), web_storage._KDF_SALT)

    def test_a_different_salt_derives_a_different_key(self):
        secret = "dedicated-key-2026-xxxxxxxxxxxxxxxx"
        mine = web_storage._cipher_from_secret(secret, salt=b"install-one-salt")
        theirs = web_storage._cipher_from_secret(secret, salt=b"install-two-salt")
        token = mine.encrypt(b"access-token")
        with self.assertRaises(web_storage.InvalidToken):
            theirs.decrypt(token)

    def test_rows_written_under_the_old_shared_salt_still_read(self):
        # The whole point of keeping legacy readers: changing the derivation
        # must migrate installs as sessions are used, not log everyone out.
        secret = "dedicated-key-2026-xxxxxxxxxxxxxxxx"
        old_row = web_storage.TOKEN_PREFIX + (
            web_storage._cipher_from_secret(secret).encrypt(b"old-token").decode("ascii")
        )
        with mock.patch.object(web_storage, "CLIENT_SECRET", secret):
            primary, legacy = web_storage._build_ciphers(b"a-fresh-install-salt")
        with (
            mock.patch.object(web_storage, "_CIPHER", primary),
            mock.patch.object(web_storage, "_LEGACY_CIPHERS", legacy),
        ):
            # Written under the old shared salt, read under the new one.
            self.assertEqual(web_storage._decrypt_token(old_row), "old-token")
            # ...and a fresh write uses the install's own key from now on.
            fresh = web_storage._encrypt_token("new-token")
            self.assertEqual(web_storage._decrypt_token(fresh), "new-token")
            with self.assertRaises(web_storage.InvalidToken):
                web_storage._cipher_from_secret(secret).decrypt(
                    fresh[len(web_storage.TOKEN_PREFIX):].encode("ascii")
                )


class FailClosedTests(unittest.TestCase):
    """No cipher, no dashboard. A log line is not a control."""

    def test_startup_refuses_when_encryption_is_unavailable(self):
        # _encrypt_token hands the value straight back when there is no cipher,
        # so this used to mean Discord access and refresh tokens sitting in the
        # database in clear text behind one warning at boot.
        with mock.patch.object(web_storage, "token_cipher_ready", return_value=False):
            with self.assertRaises(RuntimeError) as caught:
                web_storage.require_token_cipher()
        self.assertIn("clear text", str(caught.exception))

    def test_startup_proceeds_when_encryption_is_available(self):
        with mock.patch.object(web_storage, "token_cipher_ready", return_value=True):
            self.assertIsNone(web_storage.require_token_cipher())


if __name__ == "__main__":
    unittest.main()
