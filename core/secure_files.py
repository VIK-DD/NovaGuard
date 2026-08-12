"""Authenticated streaming encryption for NovaGuard data archives.

The format is deliberately small and self-describing:

    magic | scrypt salt | AES-GCM nonce | ciphertext | GCM tag

Only the encryption key belongs in the password manager.  A unique salt and
nonce are generated for every file, and the header is authenticated so it
cannot be altered without detection.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


MAGIC = b"NOVAGUARD-ENC-V1\x00"
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
MIN_SECRET_LENGTH = 32


class SecureFileError(RuntimeError):
    """Raised when encrypted data cannot be created or authenticated."""


class EncryptionConfigError(SecureFileError):
    """Raised when the dedicated archive key is missing or unsafe."""


def encryption_secret(env=None):
    env = os.environ if env is None else env
    value = str(env.get("BACKUP_ENCRYPTION_KEY") or "")
    if len(value.encode("utf-8")) < MIN_SECRET_LENGTH:
        raise EncryptionConfigError(
            f"BACKUP_ENCRYPTION_KEY must contain at least {MIN_SECRET_LENGTH} characters"
        )
    return value.encode("utf-8")


def encryption_configured(env=None):
    try:
        encryption_secret(env)
    except EncryptionConfigError:
        return False
    return True


def _derive_key(secret, salt):
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(secret)


def is_encrypted_file(path):
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with path.open("rb") as source:
            return source.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt_file(source_path, output_path, *, secret=None):
    """Encrypt ``source_path`` atomically without loading it all into memory."""
    source_path = Path(source_path)
    output_path = Path(output_path)
    if not source_path.is_file():
        raise SecureFileError(f"Source file does not exist: {source_path}")
    if source_path.resolve() == output_path.resolve():
        raise SecureFileError("Source and encrypted output must be different files")

    secret = encryption_secret() if secret is None else bytes(secret)
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(_derive_key(secret, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with source_path.open("rb") as source, temporary.open("wb") as output:
            os.chmod(temporary, 0o600)
            output.write(header)
            while chunk := source.read(CHUNK_SIZE):
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, output_path)
        os.chmod(output_path, 0o600)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return output_path


def decrypt_file(source_path, output_path, *, secret=None):
    """Authenticate and decrypt a NovaGuard encrypted file atomically."""
    source_path = Path(source_path)
    output_path = Path(output_path)
    if not source_path.is_file():
        raise SecureFileError(f"Encrypted file does not exist: {source_path}")
    if source_path.resolve() == output_path.resolve():
        raise SecureFileError("Encrypted source and decrypted output must be different files")

    minimum_size = len(MAGIC) + SALT_SIZE + NONCE_SIZE + TAG_SIZE
    file_size = source_path.stat().st_size
    if file_size < minimum_size:
        raise SecureFileError("Encrypted file is truncated")

    secret = encryption_secret() if secret is None else bytes(secret)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with source_path.open("rb") as source:
            magic = source.read(len(MAGIC))
            if magic != MAGIC:
                raise SecureFileError("File is not a NovaGuard encrypted archive")
            salt = source.read(SALT_SIZE)
            nonce = source.read(NONCE_SIZE)
            header = magic + salt + nonce
            source.seek(-TAG_SIZE, os.SEEK_END)
            tag = source.read(TAG_SIZE)
            ciphertext_size = file_size - len(header) - TAG_SIZE
            source.seek(len(header))

            decryptor = Cipher(
                algorithms.AES(_derive_key(secret, salt)),
                modes.GCM(nonce, tag),
            ).decryptor()
            decryptor.authenticate_additional_data(header)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as output:
                os.chmod(temporary, 0o600)
                remaining = ciphertext_size
                while remaining:
                    chunk = source.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise SecureFileError("Encrypted file ended before its authentication tag")
                    remaining -= len(chunk)
                    output.write(decryptor.update(chunk))
                output.write(decryptor.finalize())
                output.flush()
                os.fsync(output.fileno())
        os.replace(temporary, output_path)
        os.chmod(output_path, 0o600)
    except InvalidTag as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise SecureFileError("Encrypted file authentication failed; key or data is incorrect") from error
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return output_path
