from KiPartClient.About import (
    CONTACT, GPL_URL, LICENSE_PARAGRAPHS, client_version, version_fields,
)


def test_client_version_comes_from_metadata():
    assert client_version() == "2.0.0"


def test_license_notice_matches_gpl_howto():
    text = "\n".join(LICENSE_PARAGRAPHS)
    assert "Copyright (C) 2026 Heronitec Solutions GmbH" in text
    assert "GNU General Public License" in text
    assert "WITHOUT ANY WARRANTY" in text
    assert GPL_URL == "https://www.gnu.org/licenses/"
    assert CONTACT[0] == ("Heronitec Solutions GmbH", None)
    assert any(url == "mailto:info@heronitec-solutions.de" for _, url in CONTACT)


def test_version_fields_include_server_info():
    fields = dict(version_fields("2.0.0", "10.0.1", {
        "version": "1.4.0",
        "httpLibraryVersion": "v1",
        "apiVersion": 2,
        "schemaVersion": 18,
    }))
    assert fields["Client"] == "2.0.0"
    assert fields["KiCad"] == "10.0.1"
    assert fields["Server"] == "1.4.0"
    assert fields["HTTP library"] == "v1"
    assert fields["Sync API"] == "2"
    assert fields["Database schema"] == "18"


def test_version_fields_without_server_are_blank():
    fields = dict(version_fields("", None, None))
    assert fields["Client"] == "—"
    assert fields["Server"] == "—"
    assert fields["Database schema"] == "—"
