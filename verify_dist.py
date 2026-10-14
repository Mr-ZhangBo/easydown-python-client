"""Verify package boundaries and metadata after a build; no network."""
import email
import pathlib
import tarfile
import zipfile

dist = pathlib.Path("dist")
wheels = list(dist.glob("*.whl"))
sdists = list(dist.glob("*.tar.gz"))
assert len(wheels) == len(sdists) == 1
with zipfile.ZipFile(wheels[0]) as wheel:
    files = wheel.namelist()
    assert "easydown_api_client.py" in files
    assert all(name == "easydown_api_client.py" or name.startswith(
        "easydown_api_client-0.1.0.dist-info/") for name in files)
    assert wheel.read("easydown_api_client.py") == pathlib.Path(
        "easydown_api_client.py").read_bytes()
    metadata = email.message_from_bytes(wheel.read(
        "easydown_api_client-0.1.0.dist-info/METADATA"))
    assert metadata["Name"] == "easydown-api-client"
    assert metadata["Version"] == "0.1.0"
    assert metadata["Requires-Python"] == ">=3.10"
    assert metadata["License-Expression"] == "ISC"
    assert metadata.get_all("Requires-Dist") is None
    assert "Documentation, https://easydown.org/docs/en/api" in metadata.get_all("Project-URL")
    assert metadata.get_payload().count(
        "](https://easydown.org/docs/en/api)") == 1
    assert any(name.endswith("licenses/LICENSE") for name in files)
with tarfile.open(sdists[0]) as source:
    paths = [p.name.split("/", 1)[-1] for p in source.getmembers() if p.isfile()]
    assert set(paths) == {"easydown_api_client.py", "test_client.py", "pyproject.toml",
                          "README.md", "LICENSE", "PKG-INFO"}, paths
print("Wheel and sdist metadata, source equality and file boundaries verified.")
