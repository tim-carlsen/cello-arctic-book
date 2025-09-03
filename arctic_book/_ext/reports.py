import pathlib
import re
import warnings
from collections import defaultdict
from functools import lru_cache
import datetime
import zoneinfo

import yaml
import jinja2
from icalendar import Calendar, Event

from orcestra.utils import load_frontmatter, parse_datestr
from sphinx.util import logging


logger = logging.getLogger(__name__)


def fpath2id(fpath):
    """Extract the ID (e.g. HALO-20240801a) from a given file path."""
    return pathlib.Path(fpath).stem


def collect_all_metadata(src, subdirs=("plans", "reports"), pattern="*.md"):
    """Collect front matter from Markdown files in various given locations."""
    metadata = defaultdict(dict)
    for subdir in subdirs:
        for src_file in (src / subdir).glob(pattern):
            subdir = (
                subdir[:-1] if subdir.endswith("s") else subdir
            )  # e.g. plans -> plan
            metadata[fpath2id(src_file)][subdir] = load_frontmatter(src_file)

    return metadata


def get_local_time(dt, tz):
    return dt.astimezone(zoneinfo.ZoneInfo(tz))


def add_local_times(src, metadata):
    times = (
        ("takeoff", "departure_airport"),
        ("landing", "arrival_airport"),
    )

    with open(src / "operation" / "airport_info.yaml", "r") as fp:
        airport_info = yaml.safe_load(fp)

    return {
        **metadata,
        **{
            f"{time}_local": get_local_time(
            dt=parse_datestr(metadata[time]),
            tz=airport_info[metadata[airport]]["tzinfo"],
        ) for time, airport in times
        }
    }


def consolidate_metadata(src, metadata):
    """Merge duplicated data from flight plans and reports."""
    latest_source = "report" if "report" in metadata else "plan"

    for key in ("takeoff", "landing", "departure_airport", "arrival_airport"):
        metadata[key] = metadata[latest_source][key]
    for key in ("crew", "nickname"):
        metadata[key] = metadata[latest_source].get(key, None)
    for key in ("categories",):
        metadata[key] = metadata[latest_source].get(key, [])

    metadata["pi"] = [
        member["name"] for member in metadata["crew"] if member["job"].lower() == "pi"
    ][0]

    # Add local times for takeoff and landing
    metadata = add_local_times(src, metadata)

    # Collect relative Sphinx links to flight plans and reports
    refs = []
    for k, v in metadata.items():
        if isinstance(v, dict) and "filepath" in v:
            relpath = pathlib.Path(v["filepath"]).relative_to(
                src / "operation", walk_up=True
            )
            refs.append(f"[{k}]({relpath})")

    metadata["refs"] = refs

    return metadata


def _strftime_local_utc(dt_object):
    """Return timestr with local time (LT) and UTC."""
    # lt = f"{dt_object:%H:%M}\u00A0{dt_object.tzinfo}"
    lt = f"{dt_object:%H:%M}\u00A0LT"
    utc = f"{dt_object.astimezone(datetime.UTC):%H:%M}\u00A0UTC"

    return f"**{lt}**<br>_{utc}_"


def write_flight_table(app=None):
    """Collect flight plans/reports to create overview tables for ATR and HALO."""
    src = pathlib.Path(app.srcdir)
    metadata = collect_all_metadata(src)

    meta_by_plane = {

        "King Air": {
            "regex": "KA-[0-9]*[a-z]",
            "template": src / "_templates" / "operation_kingair.md",
            "markdown": src / "operation" / "kingair.md",
        }
    }

    for meta in meta_by_plane.values():
        regex = re.compile(meta["regex"])
        frontmatters = {
            k: consolidate_metadata(src, v)
            for k, v in sorted(metadata.items(), reverse=True)
            if regex.match(k)
        }

        with open(meta["template"], "r") as fp:
            templ = fp.read()

        with open(meta["markdown"], "w") as fp:
            env = jinja2.Environment()
            env.filters["lt_utc"] = _strftime_local_utc

            t = env.from_string(templ)
            fp.write(t.render(flights=frontmatters))



def setup(app):
    app.connect("builder-inited", write_flight_table)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
