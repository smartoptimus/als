# Repository instructions for Codex

## Purpose
This repository is a small WLOC cellular geolocation proof of concept and a language-independent description of its observed wire protocol. It is not a production API connector. Keep the PoC focused on a single lookup and readable terminal output.

## Protocol contract
- Treat `README.md` as the reference for the observed WLOC request and response format. Treat `als.py` as the executable reference implementation.
- Endpoint: `https://gs-loc.apple.com/clls/wloc`. The request body is binary even though its HTTP `Content-Type` is `application/x-www-form-urlencoded`.
- Preserve big-endian WLOC frame integers, protobuf varint field encoding, and the byte-for-byte reference request vectors.
- Request top-level cell fields: GSM/UMTS `1`, LTE `25`, NR `29`. Response cell fields: GSM/UMTS `1`, LTE `22`, NR `24`.
- GSM and UMTS share the same response field. Do not infer the RAT from that field alone.
- Convert location varints as signed two's-complement integers (not ZigZag); divide latitude and longitude by 1e8.
- A returned identity with invalid location data is `NO_LOCATION`; an area-only entry (`Cell ID=-1`) is not a cell coordinate.
- Unknown fields have unknown meaning. Preserve them when decoding is needed; do not invent semantic names or rewrite observed constants.

## Implementation rules
- Use Python 3.10+ and the standard library only. Do not add third-party runtime dependencies.
- Default output is human-readable terminal text. Keep optional `--json` and `--all-records` behavior compatible.
- Keep protocol logic separate from output formatting where possible.
- Do not add batch APIs, caching, persistence, scraping, or speculative flags without an explicit request.
- Do not add names of individuals or organizations as copyright holders. The repository uses CC0 1.0.
- Keep public documentation factual and implementation-oriented. Avoid research history, unverified conclusions, and repetitive vendor mentions.

## Verification
Run `python -m unittest discover -s tests -v` and `python -m py_compile als.py`. Compare request bodies against test vectors before and after any encoder change. Do not claim that local tests prove live server behavior. Never issue live network requests as part of unit tests.
