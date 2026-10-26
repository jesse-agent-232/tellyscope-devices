#!/usr/bin/env python3
"""Build and check the app icon packs. Python 3.9+.

  tools/icons.py sync <Core Builds checkout>   rasterise its glyphs into icons/corebuilds.zip, then index
  tools/icons.py index                         rebuild icons/index.json from the packs
  tools/icons.py check                         fail if a pack, its map or icons/index.json is invalid or stale

`check` uses the standard library only. `sync` also needs CairoSVG and Pillow (pinned in
tools/icons-requirements.txt): SVG is turned into WebP here, so the phone never parses SVG.
The file format is in README.md.
"""
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

SCHEMA = 1
ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "icons"
SIZE = 96  # px, square

COREBUILDS = {
    "id": "corebuilds",
    "name": "Core Builds",
    "licence": "MIT",
    "credit": "Icons by Core Builds (MIT)",
    "source": "https://github.com/brevityA/CoreBuildsApps",
}

# The same caps the app applies before it unpacks or decodes anything.
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_UNPACKED = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SIDE = 4096

# Same pattern the app checks before a name goes into a `pm` shell line.
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")
IMAGE = re.compile(r"[A-Za-z0-9._/-]+\.(webp|png)")
APPFILTER = re.compile(r'component="ComponentInfo\{([^/}]+)/[^}]*\}"\s+drawable="([^"]+)"')


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def path_problem(path):
    """Why an index path can't be used, or None. A path names an entry inside the pack's zip."""
    if not isinstance(path, str) or not IMAGE.fullmatch(path):
        return "not a relative .webp/.png path"
    if path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
        return "absolute, empty or dot segment"
    return None


def image_size(data):
    """(width, height) from a PNG or WebP header, or None. Reads the header only, like the app."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    return None


def check_index(index, names):
    """Problems with a pack index against the entry names of its zip."""
    errors = []
    if index.get("schema") != SCHEMA:
        return [f"schema is {index.get('schema')!r}, expected {SCHEMA}"]
    icons = index.get("icons")
    if not isinstance(icons, dict) or not icons:
        return ["icons must be a non-empty object"]
    for pkg, path in icons.items():
        if not PACKAGE.fullmatch(pkg):
            errors.append(f"{pkg!r}: not a package name")
        elif path_problem(path):
            errors.append(f"{pkg}: {path!r} is {path_problem(path)}")
        elif path not in names:
            errors.append(f"{pkg}: {path} is not in the zip")
    return errors


def check_zip(data, index=None):
    """Problems with a pack zip. With no index given, it must carry its own index.json."""
    if len(data) > MAX_DOWNLOAD:
        return [f"{len(data)} bytes, over {MAX_DOWNLOAD}"]
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a zip"]
    entries = z.infolist()
    if len(entries) > MAX_ENTRIES:
        return [f"{len(entries)} entries, over {MAX_ENTRIES}"]
    if sum(e.file_size for e in entries) > MAX_UNPACKED:
        return [f"unpacks to over {MAX_UNPACKED} bytes"]
    names = {e.filename: e for e in entries}
    if index is None:
        if "index.json" not in names:
            return ["no index.json at the root"]
        index = json.loads(z.read("index.json"))
    errors = check_index(index, names)
    for path in set(index.get("icons", {}).values()) & names.keys():
        if names[path].file_size > MAX_IMAGE_BYTES:
            errors.append(f"{path}: over {MAX_IMAGE_BYTES} bytes")
            continue
        size = image_size(z.read(path)[:64])
        if not size:
            errors.append(f"{path}: not a PNG or WebP")
        elif max(size) > MAX_SIDE:
            errors.append(f"{path}: {size[0]}x{size[1]}, over {MAX_SIDE} px")
    return errors


def appfilter(text):
    """Package -> square glyph name. Core Builds maps to its banners; the glyph drops `_banner`."""
    icons = {}
    for pkg, drawable in APPFILTER.findall(text):
        if PACKAGE.fullmatch(pkg):
            icons.setdefault(pkg, re.sub(r"_banner$", "", drawable))
    return icons


def rasterise(svg):
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(bytestring=svg, output_width=SIZE, output_height=SIZE, unsafe=False)
    out = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGBA").save(out, "WEBP", lossless=True, method=6)
    return out.getvalue()


def write_zip(path, files):
    """A byte-for-byte reproducible zip: sorted entries, fixed timestamps."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name.endswith(".webp") else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name])


def sync(upstream):
    upstream = Path(upstream)
    commit = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    glyphs = appfilter((upstream / "app/src/main/assets/appfilter.xml").read_text(encoding="utf-8"))
    files, icons, missing = {}, {}, set()
    for pkg, name in sorted(glyphs.items()):
        svg = upstream / "assets/svg" / f"{name}.svg"
        if not svg.is_file():
            missing.add(name)
            continue
        path = f"icons/{name}.webp"
        if path not in files:
            files[path] = rasterise(svg.read_bytes())
        icons[pkg] = path
    if missing:
        print(f"skipped {len(missing)} glyphs with no SVG: {', '.join(sorted(missing))}", file=sys.stderr)
    index = {"schema": SCHEMA, "name": COREBUILDS["name"], "size": SIZE, "icons": icons}
    files["index.json"] = dump(index).encode()
    ICONS.mkdir(exist_ok=True)
    write_zip(ICONS / "corebuilds.zip", files)
    (ICONS / "upstream.txt").write_text(f"{COREBUILDS['source'].split('github.com/')[1]} {commit}\n")
    write_index()
    print(f"{len(icons)} packages, {len(files) - 1} icons from Core Builds {commit[:12]}")


def build_index():
    zipped = ICONS / "corebuilds.zip"
    commit = (ICONS / "upstream.txt").read_text().split()[1]
    count = len(json.loads(zipfile.ZipFile(zipped).read("index.json"))["icons"])
    minimalist = json.loads((ICONS / "minimalist.json").read_text(encoding="utf-8"))
    packs = [
        {**COREBUILDS, "commit": commit, "file": "icons/corebuilds.zip",
         "sha256": sha256(zipped), "bytes": zipped.stat().st_size, "packages": count},
        {key: minimalist[key] for key in ("id", "name", "licence", "notice", "credit", "source", "commit", "archive", "bytes", "fit")}
        | {"map": "icons/minimalist.json", "packages": len(minimalist["icons"])},
    ]
    return {"schema": SCHEMA, "packs": packs}


def write_index():
    (ICONS / "index.json").write_text(dump(build_index()), encoding="utf-8")


def check():
    errors = []
    zipped = ICONS / "corebuilds.zip"
    errors += [f"corebuilds.zip: {e}" for e in check_zip(zipped.read_bytes())]
    minimalist = json.loads((ICONS / "minimalist.json").read_text(encoding="utf-8"))
    if not minimalist.get("archive", "").startswith("https://"):
        errors.append("minimalist.json: archive must be an https:// address")
    if minimalist.get("commit", "") not in minimalist.get("archive", ""):
        errors.append("minimalist.json: archive must be pinned to its commit")
    # The archive itself isn't ours to mirror, so only the paths are checked here.
    errors += [f"minimalist.json: {e}" for e in check_index(minimalist, set(minimalist["icons"].values()))]
    if (ICONS / "index.json").read_text(encoding="utf-8") != dump(build_index()):
        errors.append("icons/index.json is stale: run tools/icons.py index")
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        sys.exit(1)
    print("icons ok")


def main(argv):
    if argv[:1] == ["sync"] and len(argv) == 2:
        sync(argv[1])
    elif argv == ["index"]:
        write_index()
    elif argv == ["check"]:
        check()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
