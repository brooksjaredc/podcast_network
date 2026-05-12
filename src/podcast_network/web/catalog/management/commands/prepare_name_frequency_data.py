from __future__ import annotations

import csv
import json
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

DEFAULT_FIRST_NAMES_URL = (
    "https://raw.githubusercontent.com/hackerb9/ssa-baby-names/main/alldata.txt"
)
DEFAULT_LAST_NAMES_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
DEFAULT_OUTPUT_DIR = Path("data/reference/name_frequency")


class Command(BaseCommand):
    help = "Prepare local first-name and surname frequency lookup files for entity resolution."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--first-names-url", default=DEFAULT_FIRST_NAMES_URL)
        parser.add_argument("--last-names-url", default=DEFAULT_LAST_NAMES_URL)
        parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    def handle(self, *args: object, **options: object) -> None:
        output_dir = Path(str(options["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            first_names_path = tmpdir_path / "ssa_alldata.txt"
            last_names_path = tmpdir_path / "census_surnames_2010.zip"
            download(str(options["first_names_url"]), first_names_path)
            download(str(options["last_names_url"]), last_names_path)
            first_count = write_first_name_lookup(first_names_path, output_dir)
            last_count = write_last_name_lookup(last_names_path, output_dir)
        self.stdout.write(
            self.style.SUCCESS(
                f"Prepared name frequency data: {first_count} first names, "
                f"{last_count} surnames in {output_dir}."
            )
        )


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def write_first_name_lookup(source_path: Path, output_dir: Path) -> int:
    first_counts: dict[str, int] = defaultdict(int)
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for name, _sex, count, _year in reader:
            first_counts[name.casefold()] += int(count)
    total = sum(first_counts.values())
    payload = {
        "source": (
            "SSA baby names national data mirrored at "
            "https://github.com/hackerb9/ssa-baby-names; original source "
            "https://www.ssa.gov/oact/babynames/names.zip"
        ),
        "metric": "total recorded births by given name across SSA annual national files",
        "total_count": total,
        "names": {
            name: {
                "count": count,
                "per_million": round(count / total * 1_000_000, 6),
            }
            for name, count in sorted(
                first_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        },
    }
    write_json(output_dir / "first_names_ssa.json", payload)
    return len(first_counts)


def write_last_name_lookup(source_path: Path, output_dir: Path) -> int:
    names = {}
    with (
        zipfile.ZipFile(source_path) as archive,
        archive.open("Names_2010Census.csv") as raw_handle,
    ):
        reader = csv.DictReader(line.decode("utf-8") for line in raw_handle)
        for row in reader:
            count = int(row["count"])
            per_100k = float(row["prop100k"])
            names[row["name"].casefold()] = {
                "count": count,
                "rank": int(row["rank"]),
                "per_100k": per_100k,
                "per_million": round(per_100k * 10, 6),
            }
    payload = {
        "source": (
            "U.S. Census Bureau 2010 surnames: "
            "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
        ),
        "metric": (
            "surname count and rate among surnames occurring 100 or more times "
            "in the 2010 Census"
        ),
        "names": dict(sorted(names.items(), key=lambda item: item[1]["count"], reverse=True)),
    }
    write_json(output_dir / "last_names_census_2010.json", payload)
    return len(names)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
