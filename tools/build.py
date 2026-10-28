#!/usr/bin/env python3
"""Build the device lists and index.json. Python 3.9+, standard library only.

  tools/build.py sync <cleanyourtv checkout>   rewrite devices/ from its examples/, then index
  tools/build.py index                         rebuild index.json from devices/, match/, lists/ and logos/
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
# The app-wide lists in lists/, by the name the index gives them.
LISTS = ("launchers", "labels", "streaming")
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
# The Remote's sheet in dark mode; a service's `dark` fill replaces a colour that sinks into it.
DARK_SHEET = "#161D1D"
LOGO = re.compile(r"[a-z0-9]+")
PNG = b"\x89PNG\r\n\x1a\n"
# Logos are drawn at four times their size in dp and have to fit the smallest pill, 72 x 30 dp.
LOGO_MAX = (72 * 4, 30 * 4)
LOGO_BYTES = 64 * 1024


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
    active = {p["pkg"] for g in groups for p in g["packages"] if not p.get("optional")}
    # Keep wins over a list entry, and an active entry over a commented copy wherever it sits;
    # otherwise a name listed twice keeps its first entry.
    for g in groups:
        unique = []
        for p in g["packages"]:
            name = p["pkg"]
            if name in keep_names or name in seen or (p.get("optional") and name in active):
                continue
            unique.append(p)
            seen.add(name)
        g["packages"] = unique
    groups = [g for g in groups if g["packages"]]

    prose = " ".join(header)
    sdk = re.search(r"\b(?:SDK|API)\s*(\d{2})\b", prose)
    os_ = re.search(r"\b((?:Google TV|Android TV|Fire OS|Android)\s+\d+(?:\.\d+)*)", prose)
    # The first "build <token>" whose token has a digit: "the build is the same" is prose, not an id.
    build = next((m for m in re.finditer(r"\bbuild\s+([A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])", prose, re.I)
                  if re.search(r"\d", m.group(1))), None)
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
        df = out / f"{folder.name}.json"
        device = keep_commit(device, json.loads(df.read_text(encoding="utf-8")) if df.is_file() else None)
        df.write_text(dump(device), encoding="utf-8")
        written.add(f"{folder.name}.json")
    for stale in out.glob("*.json"):
        if stale.name not in written:
            stale.unlink()
    (ROOT / "upstream.txt").write_text(f"{UPSTREAM} {commit}\n", encoding="utf-8")


def keep_commit(device, old):
    """The device with the old file's source.commit when nothing else changed, so a sync's diff
    lists only new and changed lists. source.commit is then the commit the list last changed at, or older."""
    if old is None or "commit" not in old.get("source", {}):
        return device
    kept = {**device, "source": {**device["source"], "commit": old["source"]["commit"]}}
    return kept if kept == old else device


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
    def file(path):
        return {"file": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}

    return {"schema": SCHEMA, "source": {"repo": upstream[0], "commit": upstream[1]},
            "devices": devices,
            "lists": {name: file(f"lists/{name}.json") for name in LISTS},
            "logos": {f.stem: file(f"logos/{f.name}") for f in sorted((ROOT / "logos").glob("*.png"))}}


def png_size(data):
    """Width and height from a PNG's IHDR, or None if it isn't a PNG."""
    if len(data) < 24 or not data.startswith(PNG) or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def contrast(a, b):
    """WCAG contrast between two #RRGGBB colours, as the app's RemoteButtons.contrast works it out."""
    def luminance(c):
        def ch(i):
            v = int(c[i:i + 2], 16) / 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)
    x, y = luminance(a), luminance(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def check_lists():
    """Errors in lists/ and logos/: the app drops what it can't read, so a bad entry would vanish quietly."""
    errors = []

    def load(name):
        path = ROOT / "lists" / f"{name}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"lists/{name}.json: {e}")
            return None
        if data.get("schema") != SCHEMA:
            errors.append(f"lists/{name}.json: 'schema' must be {SCHEMA}")
            return None
        return data

    def package(where, name):
        if not (isinstance(name, str) and PACKAGE.fullmatch(name)):
            errors.append(f"{where}: not a package name: {name!r}")

    def text(where, obj, key, required=True):
        if key in obj or required:
            if not (isinstance(obj.get(key), str) and obj[key].strip()):
                errors.append(f"{where}: '{key}' must be a non-empty string")

    launchers = load("launchers")
    if launchers:
        seen = set()
        for i, l in enumerate(launchers.get("launchers", [])):
            where = f"lists/launchers.json: launcher {i + 1}"
            if set(l) - {"package", "name", "about"}:
                errors.append(f"{where}: unknown keys {sorted(set(l) - {'package', 'name', 'about'})}")
            package(where, l.get("package"))
            text(where, l, "name")
            text(where, l, "about", required=False)
            if l.get("package") in seen:
                errors.append(f"{where}: {l.get('package')} is listed twice")
            seen.add(l.get("package"))

    labels = load("labels")
    if labels:
        seen = set()
        for g in labels.get("groups", []):
            for pkg, label in g.get("labels", {}).items():
                where = f"lists/labels.json: {g.get('name')!r}"
                if pkg != "android":
                    package(where, pkg)
                if not (isinstance(label, str) and label.strip()):
                    errors.append(f"{where}: {pkg} needs a name")
                if pkg in seen:
                    errors.append(f"{where}: {pkg} is listed twice")
                seen.add(pkg)

    streaming = load("streaming")
    used = set()
    if streaming:
        names, packages = set(), set()
        for g in streaming.get("groups", []):
            for s in g.get("services", []):
                where = f"lists/streaming.json: {s.get('name')!r}"
                text(where, s, "name")
                if not (isinstance(s.get("packages"), list) and s["packages"]):
                    errors.append(f"{where}: 'packages' must list at least one package")
                for p in s.get("packages") or []:
                    package(where, p)
                    if p in packages:
                        errors.append(f"{where}: {p} belongs to another service too")
                    packages.add(p)
                for key in ("color", "color2", "dark"):
                    if (key == "color" or key in s) and not (isinstance(s.get(key), str) and HEX.fullmatch(s[key])):
                        errors.append(f"{where}: '{key}' must be #RRGGBB")
                dark = s.get("dark")
                if isinstance(dark, str) and HEX.fullmatch(dark) and contrast(dark, DARK_SHEET) < 3:
                    errors.append(f"{where}: 'dark' is {contrast(dark, DARK_SHEET):.2f}:1 against the dark sheet, under 3:1")
                logo = s.get("logo")
                if not (isinstance(logo, str) and LOGO.fullmatch(logo)):
                    errors.append(f"{where}: 'logo' must be lowercase letters and digits")
                elif not (ROOT / "logos" / f"{logo}.png").is_file():
                    errors.append(f"{where}: logos/{logo}.png is missing")
                used.add(logo)
                if s.get("name") in names:
                    errors.append(f"{where}: listed twice")
                names.add(s.get("name"))

    sources = ROOT / "logos" / "SOURCES.md"
    rows = set(re.findall(r"^\| *([a-z0-9]+) *\|", sources.read_text(encoding="utf-8"), re.M)) if sources.is_file() else set()
    for f in sorted((ROOT / "logos").glob("*")):
        where = f"logos/{f.name}"
        if f.name == "SOURCES.md":
            continue
        if f.stem not in rows:
            errors.append(f"{where}: needs a row in logos/SOURCES.md with its source and licence")
        if f.suffix != ".png" or not LOGO.fullmatch(f.stem):
            errors.append(f"{where}: logos are <lowercase letters and digits>.png")
            continue
        data = f.read_bytes()
        size = png_size(data)
        if size is None:
            errors.append(f"{where}: not a PNG")
        elif size[0] > LOGO_MAX[0] or size[1] > LOGO_MAX[1]:
            errors.append(f"{where}: {size[0]}x{size[1]} is over {LOGO_MAX[0]}x{LOGO_MAX[1]}")
        if len(data) > LOGO_BYTES:
            errors.append(f"{where}: {len(data)} bytes is over {LOGO_BYTES}")
        if streaming and f.stem not in used:
            errors.append(f"{where}: no service in lists/streaming.json uses it")
    return errors


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
    errors += check_lists()
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
