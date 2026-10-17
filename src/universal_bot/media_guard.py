"""Reject error bodies disguised as audio or video before a Discord upload.

The 2026-09-30 case: a 223-byte CDN error was uploaded as ``.mp4`` because the
downloader ignored HTTP status and the uploader only rejected bodies under
32 bytes or an HTML content type. A forced ``.mp4`` filename hid the rest.
"""

from __future__ import annotations

from typing import Mapping

VIDEO_MIN_BYTES = 50 * 1024
AUDIO_MIN_BYTES = 1024

_VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
_MP4_EXTS = {".mp4", ".m4v", ".mov", ".m4a", ".aac"}


def _ext(filename: str | None) -> str:
    if not filename:
        return ""
    name = filename.rsplit("/", 1)[-1].split("?", 1)[0].strip()
    dot = name.rfind(".")
    if dot <= 0:
        return ""
    return name[dot:].lower()


def _header(headers: Mapping[str, str] | None, key: str) -> str:
    if not headers:
        return ""
    want = key.lower()
    for raw_key, value in headers.items():
        if str(raw_key).lower() == want:
            return str(value).strip()
    return ""


def sniff_container(data: bytes) -> str:
    """Best-effort container from magic bytes. Error pages are not media."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"ID3"):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "audio/wav"
    head = data.lstrip()[:64].lower()
    if head.startswith((b"<html", b"<!doctype html", b"<!doctype")):
        return "text/html"
    if head.startswith((b"<?xml", b"<error", b"<")):
        return "application/xml"
    if head.startswith((b"{", b"[")):
        return "application/json"
    return "application/octet-stream"


def _claimed_kind(filename: str | None, mime: str | None) -> str:
    ext = _ext(filename)
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    mime_l = (mime or "").split(";", 1)[0].strip().lower()
    if mime_l.startswith("video/"):
        return "video"
    if mime_l.startswith("audio/"):
        return "audio"
    return ""


def _magic_ok(filename: str | None, sniffed: str) -> bool:
    ext = _ext(filename)
    if not ext:
        return sniffed not in {"text/html", "application/xml", "application/json"}
    if ext in _MP4_EXTS:
        return sniffed == "video/mp4"
    if ext in {".webm", ".mkv"}:
        return sniffed == "video/webm"
    if ext in {".ogg", ".opus"}:
        return sniffed == "audio/ogg"
    if ext == ".flac":
        return sniffed == "audio/flac"
    if ext == ".mp3":
        return sniffed == "audio/mpeg"
    if ext == ".wav":
        return sniffed == "audio/wav"
    return False


def validate_media_download(
    data: bytes,
    *,
    status: int | None = None,
    headers: Mapping[str, str] | None = None,
    filename: str | None = None,
    mime: str | None = None,
    max_bytes: int | None = None,
    min_video_bytes: int = VIDEO_MIN_BYTES,
    min_audio_bytes: int = AUDIO_MIN_BYTES,
) -> dict:
    """Return ``{ok, error, bytes, sniffed}``.

    ``error`` is empty when ``ok`` is true. Call this before ``send_with_files``.
    """
    blob = data or b""
    sniffed = sniff_container(blob)
    mime_l = (mime or "").split(";", 1)[0].strip().lower()
    out = {
        "ok": False,
        "error": "",
        "bytes": len(blob),
        "sniffed": sniffed,
        "status": status,
    }
    if status is not None and not (200 <= int(status) <= 299):
        out["error"] = "http_status"
        return out

    kind = _claimed_kind(filename, mime)
    if kind == "video" and len(blob) < min_video_bytes:
        out["error"] = "suspicious_small_file"
        return out
    if kind == "audio" and len(blob) < min_audio_bytes:
        out["error"] = "suspicious_small_file"
        return out

    if "html" in mime_l or sniffed == "text/html":
        out["error"] = "got_html_not_file"
        return out
    if sniffed in {"application/xml", "application/json"}:
        out["error"] = "not_media"
        return out

    content_length = _header(headers, "content-length")
    if content_length.isdigit():
        expected = int(content_length)
        capped = max_bytes is not None and len(blob) == max_bytes and expected > max_bytes
        if expected != len(blob) and not capped:
            out["error"] = "content_length_mismatch"
            out["content_length"] = expected
            return out

    if kind and not _magic_ok(filename or _filename_for_mime(mime_l), sniffed):
        out["error"] = "magic_mismatch"
        return out
    if not kind and sniffed == "application/octet-stream" and len(blob) < 32:
        out["error"] = "download_too_small"
        return out

    out["ok"] = True
    return out


def _filename_for_mime(mime_l: str) -> str:
    if mime_l.startswith("video/"):
        return "file.mp4" if "webm" not in mime_l else "file.webm"
    if mime_l.startswith("audio/"):
        if "mpeg" in mime_l or mime_l.endswith("/mp3"):
            return "file.mp3"
        if "ogg" in mime_l or "opus" in mime_l:
            return "file.ogg"
        if "flac" in mime_l:
            return "file.flac"
        if "wav" in mime_l:
            return "file.wav"
        return "file.m4a"
    return ""


def verify_attachment(
    *,
    sent_bytes: int,
    attachment_size: int | None,
    filename: str | None = None,
    min_video_bytes: int = VIDEO_MIN_BYTES,
) -> dict:
    """Check the size Discord stored against the bytes we sent."""
    out = {
        "ok": False,
        "error": "",
        "sent_bytes": int(sent_bytes or 0),
        "attachment_size": attachment_size,
    }
    if attachment_size is None:
        out["error"] = "attachment_size_missing"
        return out
    size = int(attachment_size)
    kind = _claimed_kind(filename, None)
    if kind == "video" and size < min_video_bytes:
        out["error"] = "suspicious_small_file"
        return out
    if kind == "audio" and size < AUDIO_MIN_BYTES:
        out["error"] = "suspicious_small_file"
        return out
    sent = int(sent_bytes or 0)
    if sent > 0 and size < max(sent // 100, 1) and size < sent:
        out["error"] = "size_mismatch"
        return out
    out["ok"] = True
    return out
