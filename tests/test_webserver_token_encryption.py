"""Dashboard token encryption supports safe migration to a dedicated key."""

import unittest
from unittest import mock

from core import webserver


@unittest.skipIf(webserver.Fernet is None, "cryptography is not installed")
class WebTokenEncryptionTests(unittest.TestCase):
    def test_dedicated_key_encrypts_new_tokens(self):
        dedicated = webserver._cipher_from_secret("dedicated-key-2026-xxxxxxxxxxxxxxxx")
        legacy = webserver._cipher_from_secret("discord-secret")

        with mock.patch.object(webserver, "_CIPHER", dedicated), mock.patch.object(
            webserver, "_LEGACY_CIPHER", legacy
        ):
            encrypted = webserver._encrypt_token("access-token")

        self.assertEqual(
            dedicated.decrypt(encrypted[len(webserver.TOKEN_PREFIX):].encode()).decode(),
            "access-token",
        )
        with self.assertRaises(webserver.InvalidToken):
            legacy.decrypt(encrypted[len(webserver.TOKEN_PREFIX):].encode())

    def test_legacy_client_secret_rows_remain_readable(self):
        dedicated = webserver._cipher_from_secret("dedicated-key-2026-xxxxxxxxxxxxxxxx")
        legacy = webserver._cipher_from_secret("discord-secret")
        encrypted = webserver.TOKEN_PREFIX + legacy.encrypt(b"old-access-token").decode()

        with mock.patch.object(webserver, "_CIPHER", dedicated), mock.patch.object(
            webserver, "_LEGACY_CIPHER", legacy
        ):
            self.assertEqual(webserver._decrypt_token(encrypted), "old-access-token")

    def test_unknown_key_fails_closed(self):
        primary = webserver._cipher_from_secret("primary-key-2026-xxxxxxxxxxxxxxxxxxx")
        unknown = webserver._cipher_from_secret("unknown-key-2026-xxxxxxxxxxxxxxxxxxx")
        encrypted = webserver.TOKEN_PREFIX + unknown.encrypt(b"token").decode()

        with mock.patch.object(webserver, "_CIPHER", primary), mock.patch.object(
            webserver, "_LEGACY_CIPHER", None
        ):
            self.assertIsNone(webserver._decrypt_token(encrypted))


if __name__ == "__main__":
    unittest.main()
