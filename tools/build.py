#!/usr/bin/env python3
"""Build the device lists and index.json. Python 3.9+, standard library only.

  tools/build.py sync <cleanyourtv checkout>   rewrite devices/ from its examples/, then index
  tools/build.py index                         rebuild index.json from devices/ and match/
  tools/build.py check                         fail if anything is invalid or index.json is stale

The file format is in README.md.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
UPSTREAM = "Gathin23/cleanyourtv"
ROOT = Path(__file__).resolve().parent.parent

# Same pattern the app checks before a name goes into a `pm` shell line.
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")
COMMENTED_PACKAGE = re.compile(r"#\s*(" + PACKAGE.pattern + r")\s*(?:#\s*(.*))?")
ACTIVE_PACKAGE = re.compile(r"(" + PACKAGE.pattern + r")\s*(?:#\s*(.*))?")
# A heading that marks its commented-out packages as load-bearing rather than merely untested.
KEEP_HEADING = re.compile(r"do not disable|don't disable|must stay|^keep\b|^kept on purpose", re.I)
UNCOMMENT = re.compile(r"uncomment", re.I)
MATCH_KEYS = ("manufacturer", "model", "device")


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def parse_list(text):
    """One debloat.txt -> the parts of a device file that come from it."""
    # Blocks are separated by blank lines or a bare "#". Prose before the first package is the header.
    blocks, block = [], []
    for line in text.split("\n") + [""]:
        line = line.strip()
        if line and line != "#":
            block.append(line)
        elif block:
            blocks.append(block)
            block = []

    header, keep, groups, seen = [], [], [], set()
    for block in blocks:
        heading, packages = [], []
        for line in block:
            m = ACTIVE_PACKAGE.fullmatch(line) or COMMENTED_PACKAGE.fullmatch(line)
            if m:
                packages.append(entry(m, optional=line.startswith("#")))
            elif not packages:
                heading.append(line.lstrip("#").strip())
        title = heading[0].rstrip(":") if heading else ""
        if not packages:
            if not groups and not keep:
                header += [line.lstrip("#").strip() for line in block]
            continue
        if KEEP_HEADING.search(title) and not UNCOMMENT.search(" ".join(heading)):
            keep += [p for p in packages if p.pop("optional", False)]
            packages = [p for p in packages if p not in keep]
        if packages:
            groups.append({"title": title, "packages": packages})

    keep_names = {p["pkg"] for p in keep}
    for g in groups:  # keep wins over a list entry; a name listed twice keeps its first entry
        unique = []
        for p in g["packages"]:
            if p["pkg"] not in keep_names and p["pkg"] not in seen:
                unique.append(p)
                seen.add(p["pkg"])
        g["packages"] = unique
    groups = [g for g in groups if g["packages"]]

    prose = " ".join(header)
    sdk = re.search(r"\b(?:SDK|API)\s*(\d{2})\b", prose)
    os_ = re.search(r"\b((?:Google TV|Android TV|Fire OS|Android)\s+\d+(?:\.\d+)*)", prose)
    build = re.search(r"\bbuild\s+([A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])", prose)
    launcher = re.search(r"Stock launcher:\s*(" + PACKAGE.pattern + r")", prose)
    name = re.split(r"\s\(|,", header[0], maxsplit=1)[0].strip() if header else ""
    return {
        "name": name,
        "tested": {
            "os": os_.group(1) if os_ else None,
            "sdk": int(sdk.group(1)) if sdk else None,
            "build": build.group(1) if build else None,
        },
        "launcher": launcher.group(1) if launcher else None,
        "keep": keep,
        "groups": groups,
    }


def entry(m, optional=False):
    e = {"pkg": m.group(1)}
    note = m.groups()[-1]
    if note:
        e["note"] = note.strip()
    if optional:
        e["optional"] = True
    return e


def sync(upstream):
    upstream = Path(upstream)
    commit = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True).stdout.strip()
    out = ROOT / "devices"
    out.mkdir(exist_ok=True)
    written = set()
    for folder in sorted((upstream / "examples").iterdir()):
        src = folder / "debloat.txt"
        if not src.is_file():
            continue
        device = {"schema": SCHEMA, "id": folder.name}
        device.update(parse_list(src.read_text(encoding="utf-8")))
        device["source"] = {"repo": UPSTREAM, "path": f"examples/{folder.name}/debloat.txt",
                            "commit": commit}
        (out / f"{folder.name}.json").write_text(dump(device), encoding="utf-8")
        written.add(f"{folder.name}.json")
    for stale in out.glob("*.json"):
        if stale.name not in written:
            stale.unlink()
    (ROOT / "upstream.txt").write_text(f"{UPSTREAM} {commit}\n", encoding="utf-8")


def build_index():
    upstream = (ROOT / "upstream.txt").read_text(encoding="utf-8").split() \
        if (ROOT / "upstream.txt").exists() else [UPSTREAM, None]
    devices = []
    for df in sorted((ROOT / "devices").glob("*.json")):
        device = json.loads(df.read_text(encoding="utf-8"))
        mf = ROOT / "match" / df.name
        devices.append({
            "id": device["id"],
            "name": device["name"],
            "match": json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else None,
            "sdk": device["tested"]["sdk"],
            "file": f"devices/{df.name}",
            "sha256": hashlib.sha256(df.read_bytes()).hexdigest(),
        })
    return {"schema": SCHEMA, "source": {"repo": upstream[0], "commit": upstream[1]},
            "devices": devices}


def check():
    errors = []
    for mf in sorted((ROOT / "match").glob("*.json")):
        try:
            rule = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"{mf.name}: {e}")
            continue
        if set(rule) - set(MATCH_KEYS):
            errors.append(f"match/{mf.name}: unknown keys {sorted(set(rule) - set(MATCH_KEYS))}")
        for key in ("manufacturer", "model"):
            if not rule.get(key):
                errors.append(f"match/{mf.name}: '{key}' is required")
        for key, values in rule.items():
            if not (isinstance(values, list) and values
                    and all(isinstance(v, str) and v.strip() for v in values)):
                errors.append(f"match/{mf.name}: '{key}' must be a list of non-empty strings")
    for df in sorted((ROOT / "devices").glob("*.json")):
        device = json.loads(df.read_text(encoding="utf-8"))
        names = [p["pkg"] for p in device["keep"]] + \
                [p["pkg"] for g in device["groups"] for p in g["packages"]]
        errors += [f"devices/{df.name}: not a package name: {n!r}"
                   for n in names if not PACKAGE.fullmatch(n)]
    index = ROOT / "index.json"
    if not index.is_file() or index.read_text(encoding="utf-8") != dump(build_index()):
        errors.append("index.json is stale: run tools/build.py index")
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


def main(argv):
    if argv == ["check"]:
        return check()
    if argv[:1] == ["sync"] and len(argv) == 2:
        sync(argv[1])
    elif argv != ["index"]:
        print(__doc__, file=sys.stderr)
        return 2
    (ROOT / "index.json").write_text(dump(build_index()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
