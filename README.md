# tellyscope-devices

Per-model debloat lists for Android TVs, Google TV devices and projectors, in a form apps can read.
[Tellyscope](https://github.com/man15h/tellyscope) fetches `index.json` from here, matches the TV it is connected to, and
suggests that model's list. Matching happens on the phone; nothing about the TV is sent anywhere.

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

`sha256` only catches a truncated or corrupt download. It comes from the same place as the file, so it
proves nothing about who wrote it. The protection is the review before merge, plus the app's own rules:
`keep` can only add to the packages an app refuses to touch, never remove from them, and an app acts
only on packages the TV itself lists.

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
| `source` | `{repo, path, commit}` | where the list came from |

An entry is `{"pkg": "<package>", "note": "<text>", "optional": true}`. `note` and `optional` appear
only when set. `optional` marks a line the list had commented out (untested, or kept on that unit): show
it, never pre-tick it. Every `pkg` matches `[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+`; `check` fails
otherwise.

How a `debloat.txt` becomes a device file: blocks are split on blank lines and bare `#` lines. Prose
before the first package is the header. Each block's first comment line is its group title. A commented
package under a heading that says "do not disable", "keep" or "kept on purpose" goes to `keep`; any
other commented package is `optional`. Quirk notes are not copied: follow `source` to read them.

### `index.json`

`{"schema", "source": {"repo", "commit"}, "devices": [{"id", "name", "match", "sdk", "file", "sha256"}]}`,
one entry per device file, with `match` copied from `match/<id>.json` (`null` when there is none) and
`sdk` from `tested.sdk`.

## Contributing

- **A list is wrong or missing:** fix it in [cleanyourtv](https://github.com/Gathin23/cleanyourtv). The
  next sync brings it here.
- **Your TV isn't recognised automatically:** add `match/<id>.json` with its `getprop` values and run
  `python3 tools/build.py index`.
- Before a pull request: `python3 -m unittest discover -s tests` and `python3 tools/build.py check`.

The sync runs daily (and on demand from the Actions tab). It rebuilds `devices/` and opens or refreshes
one pull request from `sync/cleanyourtv`; it force-pushes that branch, so don't commit to it. A pull
request opened by Actions starts no workflows, so the sync starts `Check` on that branch itself.

## Credits

The package lists are derived from cleanyourtv by Gathin and its contributors. See `NOTICE`.

## License

MIT, see `LICENSE`. The upstream lists keep their own MIT notice in `NOTICE`.
