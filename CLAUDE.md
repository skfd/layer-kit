# CLAUDE.md

- Every `*-layer` repo in `~/Code` runs this code on its next scheduled build: it is
  installed editable. Before committing a change here, run `python -m pytest -q` here
  **and** in each `*-layer` checkout.
- A layer's tests patch `requests.post`, `time.sleep` and `net.wait_for_link` through
  their modules, and `config`, `compare._try_overpass`, `history.seed` and
  `publish._git` on the layer's own modules. Keep calling `requests`, `time` and `net`
  as `module.function`, and keep taking the layer's functions as arguments.
- Functions take paths and settings as arguments and keep no state. Each layer owns
  its gap history, cache and config; nothing here may hold a layer's data.
- A behaviour a layer has not adopted yet is an argument with the old behaviour
  spelled out at the layer's call site (see `allow_undated`), not a silent change.
- Text files are LF (.gitattributes). Scripts write with `newline="\n"`; compare text
  ignoring `\r`.
