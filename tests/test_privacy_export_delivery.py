"""An export the member is entitled to must reach them, or nothing is erased."""

import gzip
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord.utils import DEFAULT_FILE_SIZE_LIMIT_BYTES  # noqa: E402

from cogs import privacy as privacy_cog  # noqa: E402


def _read(file):
    return file.fp.read()


class ExportAttachmentTests(unittest.TestCase):
    def test_an_export_within_the_limit_is_sent_as_readable_json(self):
        file, note = privacy_cog._export_attachment(
            {"user_id": "42"}, "novaguard-user-42", 10 * 1024 * 1024
        )

        self.assertEqual(file.filename, "novaguard-user-42.json")
        self.assertIsNone(note)
        self.assertIn(b'"user_id": "42"', _read(file))

    def test_an_oversized_export_is_compressed_rather_than_dropped(self):
        # Repeated records compress roughly tenfold, so compression rescues
        # every realistic export instead of sending the member away empty.
        payload = {"levels": [{"guild_id": "111", "xp": 10} for _ in range(2000)]}

        file, note = privacy_cog._export_attachment(payload, "novaguard-user-42", 4096)

        self.assertEqual(file.filename, "novaguard-user-42.json.gz")
        self.assertIn(".json.gz", note)
        body = _read(file)
        self.assertLessEqual(len(body), 4096)
        self.assertIn(b'"xp": 10', gzip.decompress(body))

    def test_an_export_too_large_even_compressed_reports_it_cannot_be_sent(self):
        # Random text does not compress, which is the only way to reach this
        # branch deliberately.
        payload = {"blob": os.urandom(4096).hex()}

        file, note = privacy_cog._export_attachment(payload, "novaguard-user-42", 1024)

        self.assertIsNone(file)
        self.assertIsNone(note)


class AttachmentLimitTests(unittest.TestCase):
    def test_the_limit_comes_from_the_guild_when_there_is_one(self):
        interaction = SimpleNamespace(guild=SimpleNamespace(filesize_limit=52428800))

        self.assertEqual(privacy_cog._attachment_limit(interaction), 52428800)

    def test_a_direct_message_falls_back_to_discords_default(self):
        # /privacy export and /privacy delete are usable in a DM, where there
        # is no guild to read a boosted limit from.
        interaction = SimpleNamespace(guild=None)

        self.assertEqual(
            privacy_cog._attachment_limit(interaction), DEFAULT_FILE_SIZE_LIMIT_BYTES
        )


class DeletionDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_deletion_that_cannot_deliver_its_export_erases_nothing(self):
        # The command promises an export and then erasure. If the export cannot
        # be delivered, erasing would destroy what the member is entitled to.
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42),
            guild=None,
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )
        cog = privacy_cog.Privacy(SimpleNamespace(get_cog=lambda name: None))
        erase = mock.AsyncMock()

        with (
            mock.patch.object(privacy_cog, "flush_live_privacy_state", mock.AsyncMock()),
            mock.patch.object(privacy_cog, "export_user_data", return_value={}),
            mock.patch.object(privacy_cog, "erase_live_user_data", erase),
            mock.patch.object(
                privacy_cog, "_export_attachment", return_value=(None, None)
            ),
            mock.patch.object(privacy_cog, "defer_interaction", mock.AsyncMock()),
            mock.patch.object(privacy_cog, "respond", mock.AsyncMock()) as respond,
        ):
            await cog.privacy_delete.callback(
                cog, interaction, privacy_cog.USER_DELETE_CONFIRMATION
            )

        erase.assert_not_awaited()
        respond.assert_awaited()


if __name__ == "__main__":
    unittest.main()
