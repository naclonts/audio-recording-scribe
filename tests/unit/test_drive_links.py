from __future__ import annotations

import pytest

from audio_recording_scribe.ingestion.drive import (
    DRIVE_DOWNLOAD_ENDPOINT,
    GoogleDriveFileRef,
    GoogleDriveFolderRef,
    UnsupportedGoogleDriveLinkError,
    build_google_drive_download_request,
    build_google_drive_folder_request,
    parse_google_drive_url,
)


@pytest.mark.parametrize(
    ("url", "expected_file_id", "expected_resource_key"),
    [
        (
            "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStuVwXyZ/view?usp=sharing",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            None,
        ),
        (
            "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStuVwXyZ/view?resourcekey=0-abc_DEF",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            "0-abc_DEF",
        ),
        (
            "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            None,
        ),
        (
            "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOpQrStuVwXyZ&resourcekey=0-abc_DEF",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            "0-abc_DEF",
        ),
    ],
)
def test_parse_google_drive_url_supports_common_public_file_links(
    url: str,
    expected_file_id: str,
    expected_resource_key: str | None,
) -> None:
    parsed = parse_google_drive_url(url)

    assert parsed.file_id == expected_file_id
    assert parsed.resource_key == expected_resource_key
    assert parsed.original_url == url


@pytest.mark.parametrize(
    ("url", "expected_folder_id", "expected_resource_key"),
    [
        (
            "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStuVwXyZ?usp=sharing",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            None,
        ),
        (
            "https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOpQrStuVwXyZ?resourcekey=0-abc_DEF",
            "1AbCdEfGhIjKlMnOpQrStuVwXyZ",
            "0-abc_DEF",
        ),
    ],
)
def test_parse_google_drive_url_supports_common_public_folder_links(
    url: str,
    expected_folder_id: str,
    expected_resource_key: str | None,
) -> None:
    parsed = parse_google_drive_url(url)

    assert isinstance(parsed, GoogleDriveFolderRef)
    assert parsed.folder_id == expected_folder_id
    assert parsed.resource_key == expected_resource_key
    assert parsed.original_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStuVwXyZ/edit",
        "https://example.com/file/d/1AbCdEfGhIjKlMnOpQrStuVwXyZ/view",
        "https://drive.google.com/open",
    ],
)
def test_parse_google_drive_url_rejects_unsupported_links(url: str) -> None:
    with pytest.raises(UnsupportedGoogleDriveLinkError):
        parse_google_drive_url(url)


def test_build_google_drive_download_request_uses_direct_download_endpoint() -> None:
    request = build_google_drive_download_request(
        GoogleDriveFileRef(file_id="1AbCdEfGhIjKlMnOpQrStuVwXyZ", resource_key="0-abc_DEF")
    )

    assert request.endpoint == DRIVE_DOWNLOAD_ENDPOINT
    assert request.query_params == (
        ("export", "download"),
        ("id", "1AbCdEfGhIjKlMnOpQrStuVwXyZ"),
        ("resourcekey", "0-abc_DEF"),
    )
    assert request.url == (
        "https://drive.google.com/uc?"
        "export=download&id=1AbCdEfGhIjKlMnOpQrStuVwXyZ&resourcekey=0-abc_DEF"
    )


def test_build_google_drive_folder_request_uses_canonical_folder_endpoint() -> None:
    request = build_google_drive_folder_request(
        GoogleDriveFolderRef(folder_id="1AbCdEfGhIjKlMnOpQrStuVwXyZ", resource_key="0-abc_DEF")
    )

    assert request.endpoint == "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStuVwXyZ"
    assert request.query_params == (("resourcekey", "0-abc_DEF"),)
    assert request.url == (
        "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStuVwXyZ?resourcekey=0-abc_DEF"
    )
