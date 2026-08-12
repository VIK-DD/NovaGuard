"""Encrypted archives are streaming, authenticated and atomic."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.secure_files import (  # noqa: E402
    EncryptionConfigError,
    SecureFileError,
    decrypt_file,
    encrypt_file,
    encryption_configured,
    encryption_secret,
    is_encrypted_file,
)


class SecureFileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.secret = b"correct horse battery staple 2026!!"
        self.plaintext = self.root / "private.zip"
        self.encrypted = self.root / "private.zip.ngbackup"
        self.restored = self.root / "restored.zip"
        self.plaintext.write_bytes((b"NovaGuard private state\n" * 100_000) + os.urandom(31))

    def test_round_trip_preserves_large_file_without_plaintext_header(self):
        encrypt_file(self.plaintext, self.encrypted, secret=self.secret)
        decrypt_file(self.encrypted, self.restored, secret=self.secret)

        self.assertTrue(is_encrypted_file(self.encrypted))
        self.assertEqual(self.restored.read_bytes(), self.plaintext.read_bytes())
        self.assertNotIn(b"NovaGuard private state", self.encrypted.read_bytes())
        self.assertEqual(self.encrypted.stat().st_mode & 0o777, 0o600)

    def test_tampering_is_detected_and_no_partial_output_survives(self):
        encrypt_file(self.plaintext, self.encrypted, secret=self.secret)
        content = bytearray(self.encrypted.read_bytes())
        content[len(content) // 2] ^= 0x01
        self.encrypted.write_bytes(content)

        with self.assertRaisesRegex(SecureFileError, "authentication failed"):
            decrypt_file(self.encrypted, self.restored, secret=self.secret)

        self.assertFalse(self.restored.exists())
        self.assertFalse((self.root / ".restored.zip.tmp").exists())

    def test_wrong_key_is_rejected(self):
        encrypt_file(self.plaintext, self.encrypted, secret=self.secret)

        with self.assertRaisesRegex(SecureFileError, "authentication failed"):
            decrypt_file(self.encrypted, self.restored, secret=b"a different secret with enough bytes")

    def test_missing_or_short_environment_key_is_rejected(self):
        for value in (None, "short"):
            env = {} if value is None else {"BACKUP_ENCRYPTION_KEY": value}
            with self.subTest(value=value):
                self.assertFalse(encryption_configured(env))
                with self.assertRaises(EncryptionConfigError):
                    encryption_secret(env)

        self.assertTrue(encryption_configured({"BACKUP_ENCRYPTION_KEY": "x" * 48}))

    def test_source_and_destination_must_differ(self):
        with self.assertRaisesRegex(SecureFileError, "different files"):
            encrypt_file(self.plaintext, self.plaintext, secret=self.secret)


if __name__ == "__main__":
    unittest.main()
