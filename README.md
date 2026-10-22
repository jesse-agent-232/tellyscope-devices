# tellyscope-devices

Per-model debloat lists for Android TVs, Google TV devices and projectors, in a form apps can read.
[Tellyscope](https://github.com/man15h/tellyscope) fetches `index.json` from here, matches the TV it is connected to, and
suggests that model's list. Matching happens on the phone; nothing about the TV is sent anywhere.

The lists come from [cleanyourtv](https://github.com/Gathin23/cleanyourtv) (MIT), which has one
hand-checked `debloat.txt` per TV model. A daily sync turns them into JSON and opens a pull request
here. Nothing reaches apps until a maintainer merges it.

The file format is documented in this README once the first build lands.

## Credits

The package lists are derived from cleanyourtv by Gathin and its contributors. See `NOTICE`.

## License

MIT, see `LICENSE`. The upstream lists keep their own MIT notice in `NOTICE`.
