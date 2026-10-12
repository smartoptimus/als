# Instructions for Claude Code

Read `README.md` for the observed WLOC wire protocol and `AGENTS.md` for the repository engineering rules. Follow the rules below when you change the code or documentation.

## Scope
- This is a minimal CLI PoC for GSM, UMTS, LTE, and NR lookups. It prints readable output to the terminal.
- The README must give enough binary and protobuf detail to implement a separate connector in another language.
- Do not turn the PoC into a production service or add dependencies unless explicitly requested.

## Protocol invariants
- Keep the binary WLOC framing, protobuf tags, field order, fixed request values, and reference hex vectors compatible with `als.py`.
- GSM/UMTS use request and response field `1`; LTE uses request `25` / response `22`; NR uses request `29` / response `24`.
- Decode signed coordinates as two's-complement varints divided by 100000000, not ZigZag.
- Separate exact cell coordinates, invalid coordinates, and area-only (`Cell ID=-1`) entries. Do not present an area-only coordinate as a location for a specific cell.
- A protocol field without a confirmed meaning must stay numeric and undocumented beyond observed wire type and values.

## Working process
1. Review the relevant section of `README.md` and matching code in `als.py`.
2. Make the smallest compatible change.
3. Run `python -m unittest discover -s tests -v` and `python -m py_compile als.py`.
4. Report the changes and local verification accurately; live network tests are separate.

## Repository policy
- Preserve human-readable terminal output as the default. `--json` is optional.
- No research diary, speculative protocol claims, or company/author attribution.
- The repository uses CC0 1.0 Universal. Do not alter the license without an explicit instruction.
- Mention the remote provider only when needed to state the endpoint, affiliation disclaimer, or a technical fact.
