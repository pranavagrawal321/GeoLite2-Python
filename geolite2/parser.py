from pathlib import Path
from typing import Callable, Dict
import json
import maxminddb
import shutil
import subprocess
import tempfile
import urllib.request

from .exceptions import UnknownParserType, UpdateError


ROOT_PATH = Path(__file__).resolve().parent

GITHUB_REPO = "https://github.com/pranavagrawal321/GeoLite2-Python.git"
GITHUB_API_BASE = (
    "https://api.github.com/repos/"
    "pranavagrawal321/GeoLite2-Python/contents/geolite2/data"
)

Handler = Callable[[maxminddb.Reader, str], dict | None]


class Parser:
    """
    GeoLite2 parser with git / api / local update strategies.
    """

    _registry: Dict[str, dict] = {}

    def __init__(self, data_path: Path | None = None):
        self._data_path = data_path or (ROOT_PATH / "data")
        self._data_path.mkdir(parents=True, exist_ok=True)
        self._readers: Dict[str, maxminddb.Reader] = {}

    @classmethod
    def register(cls, name: str, db_file: str):
        def decorator(func: Handler):
            cls._registry[name] = {
                "db_file": db_file,  # filename only
                "handler": func,
            }
            return func
        return decorator

    def _get_reader(self, name: str) -> maxminddb.Reader:
        if name not in self._registry:
            raise UnknownParserType(name)

        if name not in self._readers:
            filename = self._registry[name]["db_file"]
            path = self._data_path / filename
            self._readers[name] = maxminddb.open_database(path)

        return self._readers[name]

    def _close_readers(self):
        for reader in self._readers.values():
            reader.close()
        self._readers.clear()

    def parse(self, ip: str, name: str):
        reader = self._get_reader(name)
        return self._registry[name]["handler"](reader, ip)

    # ──────────────────────────────
    # Update entrypoint
    # ──────────────────────────────
    def update(self, method: str = "git", path: str | None = None):
        self._close_readers()

        print("Updating GeoLite2 data...")

        if method == "git":
            self._update_via_git()
        elif method == "api":
            self._update_via_api()
        elif method == "local":
            if not path:
                raise UpdateError("Local update requires path")
            self._update_via_local(Path(path))
        else:
            raise UpdateError(f"Unknown update method: {method}")

        print("GeoLite2 data updated successfully.")

    def _update_via_git(self):
        if shutil.which("git") is None:
            raise UpdateError("git is not available on system")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            try:
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--depth=1",
                        "--filter=blob:none",
                        "--sparse",
                        GITHUB_REPO,
                        str(tmp),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                subprocess.run(
                    ["git", "sparse-checkout", "set", "geolite2/data"],
                    cwd=tmp,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                src = tmp / "geolite2" / "data"
                self._replace_data_dir(src)

            except subprocess.CalledProcessError as exc:
                raise UpdateError("Git update failed") from exc

    def _update_via_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            print("Fetching file list from GitHub API")

            with urllib.request.urlopen(GITHUB_API_BASE, timeout=30) as resp:
                files = json.loads(resp.read().decode())

            for item in files:
                if item["type"] != "file":
                    continue

                name = item["name"]
                download_url = item["download_url"]
                target = tmp / name

                print(f"Downloading {name}")
                with urllib.request.urlopen(download_url, timeout=30) as resp:
                    target.write_bytes(resp.read())

            self._replace_data_dir(tmp)

    def _update_via_local(self, source: Path):
        if not source.exists():
            raise UpdateError(f"Local path does not exist: {source}")
        self._replace_data_dir(source)

    def _replace_data_dir(self, source: Path):
        tmp = self._data_path.with_suffix(".tmp")

        if tmp.exists():
            shutil.rmtree(tmp)

        shutil.copytree(source, tmp)

        if self._data_path.exists():
            shutil.rmtree(self._data_path)

        tmp.replace(self._data_path)

    def __getattr__(self, name: str):
        if name in self._registry:
            return lambda ip: self.parse(ip, name)
        raise AttributeError(name)


@Parser.register("asn", "GeoLite2-ASN.mmdb")
def parse_asn(reader, ip):
    return reader.get(ip)


@Parser.register("city", "GeoLite2-City.mmdb")
def parse_city(reader, ip):
    return reader.get(ip)


@Parser.register("country", "GeoLite2-Country.mmdb")
def parse_country(reader, ip):
    return reader.get(ip)
