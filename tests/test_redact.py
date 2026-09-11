import io
import logging
import unittest

from universal_bot.redact import (
    ChunkStreamRedactor,
    RedactingFilter,
    RedactingFormatter,
    SecretRedactor,
)


class TestRedact(unittest.TestCase):
    def test_literal_and_pattern_redaction(self):
        redactor = SecretRedactor(known_secrets=["super_secret_password_123"])
        # Construct synthetic token at runtime to avoid static false positives in secret scanners
        fake_token = ".".join(["MTA2Mzg5MjQ4MTQ2NzE1NDQzMg", "G9xYwZ", "abcde12345_ghijklmnOPQRSTUVWXYZ"])
        text = f"Connecting with pass super_secret_password_123 and token {fake_token}"
        redacted = redactor.redact(text)
        self.assertNotIn("super_secret_password_123", redacted)
        self.assertNotIn("MTA2Mzg5MjQ4MTQ2NzE1NDQzMg", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redacting_formatter_and_traceback(self):
        redactor = SecretRedactor(known_secrets=["TOP_SECRET_KEY_XYZ"])
        formatter = RedactingFormatter(redactor, fmt="%(levelname)s: %(message)s")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)

        logger = logging.getLogger("test_redactor_logger")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        try:
            raise ValueError("Failure exposing TOP_SECRET_KEY_XYZ in exception message")
        except ValueError:
            logger.exception("An error occurred with secret TOP_SECRET_KEY_XYZ")

        output = stream.getvalue()
        self.assertNotIn("TOP_SECRET_KEY_XYZ", output)
        self.assertIn("[REDACTED]", output)

    def test_chunk_stream_redactor_boundary_overlap(self):
        secret = "VERY_CONFIDENTIAL_TOKEN_9999"
        redactor = SecretRedactor(known_secrets=[secret])
        chunk_redactor = ChunkStreamRedactor(redactor, max_overlap=len(secret) + 10)

        # Split secret right down the middle across two chunks
        split_idx = 10
        chunk1 = f"Prefix data {secret[:split_idx]}"
        chunk2 = f"{secret[split_idx:]} suffix data"

        out1 = chunk_redactor.process_chunk(chunk1)
        out2 = chunk_redactor.process_chunk(chunk2)
        out_tail = chunk_redactor.flush()

        full_output = out1 + out2 + out_tail
        self.assertNotIn(secret, full_output)
        self.assertIn("[REDACTED]", full_output)


if __name__ == "__main__":
    unittest.main()
