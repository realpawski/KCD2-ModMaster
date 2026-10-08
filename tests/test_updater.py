from app import updater


def _release(tag, *names, prerelease=False):
    return {"tag_name": tag, "name": tag, "body": "", "html_url": "", "prerelease": prerelease,
            "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{n}", "size": 10} for n in names]}


def test_version_ordering():
    assert updater.is_newer("0.9.1", "0.9.0")
    assert updater.is_newer("v1.0.0", "1.0.0-beta.2")
    assert updater.is_newer("1.0.0-beta.10", "1.0.0-beta.2")
    assert not updater.is_newer("0.9.0", "0.9.0")
    assert not updater.is_newer("garbage", "0.9.0")


def test_latest_release_needs_an_installer(monkeypatch):
    import json
    data = [
        _release("v1.1.0", "notes.txt"),
        _release("v1.0.0", "KCD2ModMaster-1.0.0-Setup.exe", "SHA256SUMS.txt"),
        _release("v1.2.0-beta.1", "KCD2ModMaster-1.2.0-beta.1-Setup.exe", prerelease=True),
    ]
    monkeypatch.setattr(updater, "_get", lambda url, timeout: json.dumps(data).encode())
    assert updater.latest_release(include_prerelease=False).version == "1.0.0"
    best = updater.latest_release(include_prerelease=True)
    assert best.version == "1.2.0-beta.1" and best.checksum_url == ""
