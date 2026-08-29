"""Dashboard token encryption supports safe migration to a dedicated key."""

import unittest
from unittest import mock

from core import web_storage


@unittest.skipIf(web_storage.Fernet is None, "cryptography is not installed")
class WebTokenEncryptionTests(unittest.TestCase):
    def test_dedicated_key_encrypts_new_tokens(self):
        dedicated = web_storage._cipher_from_secret("dedicated-key-2026-xxxxxxxxxxxxxxxx")
        legacy = web_storage._cipher_from_secret("discord-secret")

        with mock.patch.object(web_storage, "_CIPHER", dedicated), mock.patch.object(
            web_storage, "_LEGACY_CIPHER", legacy
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

        with mock.patch.object(web_storage, "_CIPHER", dedicated), mock.patch.object(
            web_storage, "_LEGACY_CIPHER", legacy
        ):
            self.assertEqual(web_storage._decrypt_token(encrypted), "old-access-token")

    def test_unknown_key_fails_closed(self):
        primary = web_storage._cipher_from_secret("primary-key-2026-xxxxxxxxxxxxxxxxxxx")
        unknown = web_storage._cipher_from_secret("unknown-key-2026-xxxxxxxxxxxxxxxxxxx")
        encrypted = web_storage.TOKEN_PREFIX + unknown.encrypt(b"token").decode()

        with mock.patch.object(web_storage, "_CIPHER", primary), mock.patch.object(
            web_storage, "_LEGACY_CIPHER", None
        ):
            self.assertIsNone(web_storage._decrypt_token(encrypted))


if __name__ == "__main__":
    unittest.main()
