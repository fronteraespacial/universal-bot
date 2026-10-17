"""Santi 2026-09-30: a 223-byte error body must not upload as .mp4."""

import unittest

from universal_bot.media_guard import validate_media_download, verify_attachment


STUB_223 = (
    b'<?xml version="1.0"?><Error><Code>BlobNotFound</Code></Error>'
).ljust(223, b" ")


def _mp4(n: int = 50 * 1024) -> bytes:
    body = b"isom" + b"\x00\x00\x00\x00" + b"isomiso2mp41"
    head = (8 + len(body)).to_bytes(4, "big") + b"ftyp" + body
    if n < len(head):
        raise ValueError("n too small")
    return head + b"\x00" * (n - len(head))


def legacy_would_upload(data: bytes, mime: str) -> bool:
    """The gate that accepted the broken file: <32 bytes or html mime only."""
    if len(data) < 32:
        return False
    if "html" in (mime or ""):
        return False
    return True


class TestMediaGuard(unittest.TestCase):
    def test_santi_stub_passes_legacy_and_fails_guard(self):
        self.assertTrue(legacy_would_upload(STUB_223, "video/mp4"))
        verdict = validate_media_download(
            STUB_223,
            status=200,
            headers={"content-type": "video/mp4", "content-length": "223"},
            filename="How_To_Orbit_8db623fe72.mp4",
            mime="video/mp4",
        )
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["error"], "suspicious_small_file")
        self.assertEqual(verdict["bytes"], 223)

    def test_http_error_status_rejected_even_with_real_header(self):
        verdict = validate_media_download(
            _mp4(),
            status=403,
            filename="clip.mp4",
            mime="video/mp4",
        )
        self.assertEqual(verdict["error"], "http_status")

    def test_content_length_mismatch(self):
        data = _mp4(60 * 1024)
        verdict = validate_media_download(
            data,
            status=200,
            headers={"content-length": str(5_774_658)},
            filename="clip.mp4",
            mime="video/mp4",
        )
        self.assertEqual(verdict["error"], "content_length_mismatch")

    def test_real_sized_mp4_accepted(self):
        data = _mp4(60 * 1024)
        verdict = validate_media_download(
            data,
            status=200,
            headers={"content-length": str(len(data))},
            filename="How_To_Orbit_8db623fe72.mp4",
            mime="video/mp4",
        )
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["sniffed"], "video/mp4")

    def test_ftyp_under_50kb_still_rejected(self):
        verdict = validate_media_download(
            _mp4(4096),
            status=200,
            filename="tiny.mp4",
            mime="video/mp4",
        )
        self.assertEqual(verdict["error"], "suspicious_small_file")

    def test_zeros_named_mp4_are_magic_mismatch(self):
        verdict = validate_media_download(
            b"\x00" * (60 * 1024),
            status=200,
            headers={"content-length": str(60 * 1024)},
            filename="clip.mp4",
            mime="application/octet-stream",
        )
        self.assertEqual(verdict["error"], "magic_mismatch")

    def test_html_page_rejected(self):
        page = b"<!DOCTYPE html><html><body>no video</body></html>" + b" " * (60 * 1024)
        verdict = validate_media_download(
            page,
            status=200,
            filename="page.mp4",
            mime="text/html",
        )
        self.assertEqual(verdict["error"], "got_html_not_file")

    def test_attachment_223_does_not_count_as_delivered(self):
        check = verify_attachment(
            sent_bytes=223,
            attachment_size=223,
            filename="How_To_Orbit_8db623fe72.mp4",
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["error"], "suspicious_small_file")

    def test_attachment_matching_real_size(self):
        check = verify_attachment(
            sent_bytes=5_774_658,
            attachment_size=5_774_658,
            filename="How_To_Orbit_8db623fe72.mp4",
        )
        self.assertTrue(check["ok"])


if __name__ == "__main__":
    unittest.main()
