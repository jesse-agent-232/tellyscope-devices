# tellyscope-devices

Per-model debloat lists for Android TVs, Google TV devices and projectors, in a form apps can read.
[Tellyscope](https://github.com/man15h/tellyscope) fetches `index.json` from here, matches the TV it is connected to, and
suggests that model's list. Matching happens on the phone; nothing about the TV is sent anywhere.

It also holds the lists anyone can improve without an app release: the launchers Tellyscope offers,
the names it shows for apps, and the streaming services the Remote has buttons for, with their logos.

The lists come from [cleanyourtv](https://github.com/Gathin23/cleanyourtv) (MIT), which has one
hand-checked `debloat.txt` per TV model. A daily sync turns them into JSON and opens a pull request
here. Nothing reaches apps until a maintainer merges it.

## Layout

| Path | Written by | What it is |
|---|---|---|
| `devices/<id>.json` | the sync | One TV model's list. `<id>` is the cleanyourtv folder name. |
| `match/<id>.json` | people | How to recognise that TV. The sync never writes here. |
| `index.json` | `tools/build.py index` | Every device, with its match rule or `null`: what an app downloads first. |
| `upstream.txt` | the sync | The cleanyourtv commit `devices/` was built from. |
| `lists/launchers.json` | people | Home screens Tellyscope can install, and the line it shows for each. |
| `lists/labels.json` | people | App names to show when the TV doesn't give one. |
| `lists/streaming.json` | people | Streaming services the Remote can have a button for. |
| `logos/<logo>.png` | people | Each service's logo, named in `streaming.json`. |
| `logos/SOURCES.md` | people | Where each logo came from, and its licence. |

A device with no `match/` file is still in the index, with `"match": null`: an app can't recognise it,
but the user can pick it. A match rule whose device is gone is skipped.

## How an app uses it

1. Download `index.json` (cache it, revalidate with the ETag).
2. Read `ro.product.manufacturer`, `ro.product.model`, `ro.product.device` and `ro.build.version.sdk`
   from the TV, and look for an entry whose `match` fits. Matching is done on the phone. With no fit,
   let the user pick their TV from the index by `name`.
3. Download only that entry's `file` and check it against `sha256`.
4. Show the list. Pre-tick only when the entry was matched (or picked) and the TV's SDK equals `sdk`, and only packages
   that are installed, enabled and not marked `optional`. Anything weaker is shown unticked.

An app that sees a `schema` it doesn't know shows no suggestions.

The files under `lists/` and `logos/` work the same way: the index gives each one's `file` and
`sha256`, so an app downloads one again only when its `sha256` changes.

`sha256` only catches a truncated or corrupt download. It comes from the same place as the file, so it
proves nothing about who wrote it. The protection is the review before merge, plus the app's own rules:
`keep` can only add to the packages an app refuses to touch, never remove from them, and an app acts
only on packages the TV itself lists.

## Use your own lists

1. Fork this repo and edit the lists.
2. Run `python3 tools/build.py index`, then `python3 tools/build.py check`, so `index.json` stays on
   schema 1 with fresh `sha256` values.
3. In Tellyscope 0.2.0 or later, open Settings → Debloat lists → Change and paste the address of the
   folder that holds `index.json`, like `https://raw.githubusercontent.com/<you>/tellyscope-devices/main/`.
   Reset to default switches back.

Protected apps stay protected whatever a list says. Your source supplies every list and logo; which
launchers may turn on an accessibility service is decided inside the app, never by a list.

## File format

All files are plain JSON (UTF-8, no comments).

### `match/<id>.json`

| Field | Type | |
|---|---|---|
| `manufacturer` | list of strings, required | `ro.product.manufacturer`, compared case-insensitively |
| `model` | list of strings, required | `ro.product.model`, compared case-insensitively |
| `device` | list of strings, optional | `ro.product.device` (the codename); when present it must match too |

A TV matches when each field present has one value equal to the TV's property. Use the TV's own
`getprop` output, not the retail name.

### `devices/<id>.json`

| Field | Type | |
|---|---|---|
| `schema` | integer | `1` |
| `id` | string | the cleanyourtv folder name |
| `name` | string | from the list's first line |
| `tested.os`, `tested.sdk`, `tested.build` | string, integer, string, or `null` | the firmware the list was made on, read from the list's header |
| `launcher` | package name or `null` | the stock launcher, for display only: an app must ask the TV which app is Home |
| `keep` | list of entries | packages the list says must stay enabled on this model |
| `groups` | list of `{title, packages}` | the list itself, in its order and grouping |
| `source` | `{repo, path, commit}` | where the list came from; `commit` is the sync that last changed this file, so an unchanged list keeps its older commit (`upstream.txt` has the latest) |

An entry is `{"pkg": "<package>", "note": "<text>", "optional": true}`. `note` and `optional` appear
only when set. `optional` marks a line the list had commented out (untested, or kept on that unit): show
it, never pre-tick it. Every `pkg` matches `[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+`; `check` fails
otherwise.

How a `debloat.txt` becomes a device file: blocks are split on blank lines and bare `#` lines. Prose
before the first package is the header. Each block's first comment line is its group title. A commented
package under a heading that says "do not disable", "keep" or "kept on purpose" goes to `keep`; any
other commented package is `optional`. Quirk notes are not copied: follow `source` to read them.

### `lists/launchers.json`

`{"schema": 1, "launchers": [{"package", "name", "about"}]}`. `about` is optional: a launcher with one
is offered in Install a home screen, in file order. No other keys; in particular a list can't ask for
an accessibility service.

### `lists/labels.json`

`{"schema": 1, "groups": [{"name", "labels": {"<package>": "<name>"}}]}`. Groups are only for people
reading the file. A package appears once across all groups; `android` is allowed as well.

### `lists/streaming.json`

`{"schema": 1, "groups": [{"name", "services": [...]}]}`, one service per Remote button:

| Field | Type | |
|---|---|---|
| `name` | string | shown under the button |
| `packages` | list of package names | its TV apps, the usual one first; a package belongs to one service only |
| `color` | `#RRGGBB` | the button's brand colour |
| `color2` | `#RRGGBB`, optional | a gradient towards this colour |
| `dark` | `#RRGGBB`, optional | the fill in dark mode, for a colour that would sink into the dark sheet |
| `logo` | lowercase letters and digits | names `logos/<logo>.png` |

### `logos/<logo>.png`

A PNG at four times its size in dp, at most 288 x 120 pixels (it has to fit the smallest button, 72 x
30 dp) and 64 KB. White or black on transparent reads best: the app recolours it on dark brand
colours. Every logo is used by a service and has a row in `logos/SOURCES.md`.

### `index.json`

`{"schema", "source": {"repo", "commit"}, "devices": [{"id", "name", "match", "sdk", "file", "sha256"}], "lists": {"<name>": {"file", "sha256"}}, "logos": {"<logo>": {"file", "sha256"}}}`,
one `devices` entry per device file, with `match` copied from `match/<id>.json` (`null` when there is
none) and `sdk` from `tested.sdk`; `lists` has `launchers`, `labels` and `streaming`.

## Contributing

- **A TV's debloat list is wrong or missing:** fix it in [cleanyourtv](https://github.com/Gathin23/cleanyourtv). The
  next sync brings it here.
- **Your TV isn't recognised automatically:** add `match/<id>.json` with its `getprop` values and run
  `python3 tools/build.py index`.
- **A streaming service, launcher or app name is missing:** add it to the file under `lists/` (and its
  logo under `logos/`) and run `python3 tools/build.py index`.
- **A new logo** needs a source that is CC0 (like [Simple Icons](https://simpleicons.org)) or tagged
  PD-textlogo on Wikimedia Commons, and a row in `logos/SOURCES.md` with its URL and licence. With
  neither, set the service's name in plain type instead. `check` fails on a logo without a row.
- Before a pull request: `python3 -m unittest discover -s tests` and `python3 tools/build.py check`.

The sync runs daily (and on demand from the Actions tab). It rebuilds `devices/` and opens or refreshes
one pull request from `sync/cleanyourtv`; it force-pushes that branch, so don't commit to it. A pull
request opened by Actions starts no workflows, so the sync starts `Check` on that branch itself.

## Credits

The package lists are derived from cleanyourtv by Gathin and its contributors. See `NOTICE`.

## License

MIT, see `LICENSE`. The upstream lists keep their own MIT notice in `NOTICE`.
