"""Centralized redaction filter and stream sanitizer for tokens, secrets, and tracebacks."""

import logging
import re
from typing import Iterable, List, Optional, Set

# Generic patterns for API keys and tokens
TOKEN_PATTERNS = [
    re.compile(r"([a-zA-Z0-9_-]{24}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,38})"),  # Discord bot token
    re.compile(r"(AIzaSy[a-zA-Z0-9_-]{33})"),                                      # Google API Key
    re.compile(r"(sk-[a-zA-Z0-9]{32,64})"),                                        # OpenAI standard key
    re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),              # Bearer tokens
]


class SecretRedactor:
    """Sanitizes text by masking known literal secrets and common token patterns."""

    def __init__(self, known_secrets: Optional[Iterable[str]] = None, mask: str = "[REDACTED]"):
        self.mask = mask
        self._exact_secrets: Set[str] = set()
        if known_secrets:
            for s in known_secrets:
                s_clean = s.strip()
                if len(s_clean) >= 6:  # Avoid masking trivial substrings
                    self._exact_secrets.add(s_clean)

    def add_secret(self, secret: str) -> None:
        clean = secret.strip()
        if len(clean) >= 6:
            self._exact_secrets.add(clean)

    def redact(self, text: str) -> str:
        if not text:
            return ""

        # Exact literals first
        result = text
        for s in self._exact_secrets:
            if s in result:
                result = result.replace(s, self.mask)

        # Regex patterns
        for pat in TOKEN_PATTERNS:
            result = pat.sub(self.mask, result)

        return result


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts secrets from formatted messages and tracebacks."""

    def __init__(self, redactor: SecretRedactor, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return self.redactor.redact(formatted)


class RedactingFilter(logging.Filter):
    """Logging filter that sanitizes record.msg and arguments."""

    def __init__(self, redactor: SecretRedactor):
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redactor.redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.redactor.redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.redactor.redact(v) if isinstance(v, str) else v for v in record.args)
        return True


class ChunkStreamRedactor:
    """Redacts secrets across streaming chunk boundaries using an overlap buffer."""

    def __init__(self, redactor: SecretRedactor, max_overlap: int = 128):
        self.redactor = redactor
        self.max_overlap = max_overlap
        self._buffer = ""

    def _find_overlap(self, text: str) -> int:
        """Find the length of the longest suffix of text that could be a prefix of an incomplete secret."""
        if not text:
            return 0
        longest = 0
        # Check against known exact secrets
        for s in self.redactor._exact_secrets:
            max_check = min(len(text), len(s) - 1, self.max_overlap)
            for k in range(max_check, 0, -1):
                if text.endswith(s[:k]):
                    if k > longest:
                        longest = k
                    break
        return min(longest, self.max_overlap)

    def process_chunk(self, chunk: str) -> str:
        """Process incoming chunk, emitting redacted text while retaining an overlap tail."""
        combined = self._buffer + chunk
        if not combined:
            return ""

        overlap = self._find_overlap(combined)
        if overlap == 0:
            self._buffer = ""
            return self.redactor.redact(combined)

        self._buffer = combined[-overlap:]
        safe_part = combined[:-overlap]
        return self.redactor.redact(safe_part)

    def flush(self) -> str:
        """Flush remaining buffer at end of stream."""
        if not self._buffer:
            return ""
        res = self.redactor.redact(self._buffer)
        self._buffer = ""
        return res
