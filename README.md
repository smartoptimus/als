# WLOC Cellular Lookup — Protocol Reference and PoC

This repository contains a small, standard-library-only Python 3.10+ **proof of concept** (PoC). It sends a cellular lookup request to the WLOC endpoint and prints the decoded response in the terminal. The documentation describes the **observed wire protocol** so that an engineer can write a separate client in another language. The PoC is not an SDK or a production connector.

**Status of this interface:** The endpoint is undocumented. The byte layouts below reproduce successful exchanges. Do not assign a meaning to an unknown protocol field. Do not assume that an observed response size, record order, or server behavior is a permanent contract. This is an independent, unofficial protocol reference. Access to the remote endpoint is subject to applicable terms and laws; the repository license does not grant access to that endpoint.


## Working with coding agents

- [AGENTS.md](AGENTS.md) gives repository instructions for OpenAI Codex and other tools that support `AGENTS.md`.
- [CLAUDE.md](CLAUDE.md) gives the corresponding instructions for Claude Code.

Both files use the same protocol rules. The README is the reference for the observed wire format. Keep fixed binary vectors unchanged unless a change is supported by verified data.

## 1. Quick start

```console
python als.py gsm 262 2 350 9761
python als.py umts 250 20 27811 3302913
python als.py lte 262 1 18000 27086850
python als.py nr 234 10 149792 231735821
```

Windows: `py -3 als.py lte 262 1 18000 27086850`.

```text
python als.py {gsm,umts,lte,nr} MCC MNC AREA CELL [--timeout SECONDS] [--all-records] [--json]
```

The **default output is a terminal report**, not JSON. `--all-records` prints additional cell and area-only records. `--json` is optional and is useful for comparing a new decoder with the PoC. The program does not save files.

Example of terminal output (coordinates from a previously observed GSM response; the ellipsis is illustrative):

```text
=== WLOC GSM 262/2/350/9761 ===
HTTP: 200 | RESPONSE: ... bytes | RECORDS: 1
LOOKUP: EXACT
REQUESTED CELL:
  GSM   262/2/350/9761 lat,lon=51.07746887,13.72264003 accuracy_m=2302
ADDITIONAL CELLS (0):
  none
AREA-ONLY LAC/TAC RECORDS (0):
  none
RESPONSE_SHA256: ...
NOTE: Area-only records are not individual cell locations.
SUMMARY: GSM 262/2/350/9761 EXACT
```

### Input identifiers

| RAT | `AREA` | `CELL` | Maximum cell identity in this PoC |
|---|---|---|---:|
| GSM | Location Area Code (`LAC`) | GSM Cell Identity (`CI`) | 65,535 (16 bits) |
| UMTS | `LAC` | Full UTRAN Cell Identity (`UC-ID`) | 268,435,455 (28 bits) |
| LTE | Tracking Area Code (`TAC`) | E-UTRAN Cell Identity (`ECI`) | 268,435,455 (28 bits) |
| NR | `TAC` | NR Cell Identity (`NCI`) | 68,719,476,735 (36 bits) |

For a 12-bit UMTS RNC ID and 16-bit local C-ID, `UC-ID = (RNC_ID << 16) | C_ID`. For example, `RNC_ID=50` and `C_ID=26113` give `UC-ID=3302913`. Pass the *full* UC-ID. For NR, use a 64-bit integer type; a 32-bit type cannot represent all 36-bit NCIs.

The client validates MCC 1–999, MNC 0–999, LAC/LTE TAC 0–65,535, and NR TAC 0–16,777,215. These are **PoC input limits**, not an exhaustive description of server validation. Treat MNC as its numerical value in this protocol; preserve its original 2- or 3-digit presentation separately if needed in another system.

## 2. Transport and binary framing

### HTTP request

```http
POST /clls/wloc HTTP/1.1
Host: gs-loc.apple.com
User-Agent: locationd/2964.0.8 CFNetwork/3826.600.41 Darwin/24.6.0
Accept: */*
Accept-Language: en-GB,en-US;q=0.9,en;q=0.8
Content-Type: application/x-www-form-urlencoded
Content-Length: <binary-body-length>

<binary request body>
```

URL: `https://gs-loc.apple.com/clls/wloc` (HTTPS). **The body is binary even though the Content-Type is `application/x-www-form-urlencoded`.** Do not URL-encode or JSON-encode the body. The values above are the exact values used by this PoC, not a statement that each HTTP header is mandatory. `Content-Length` is calculated by the HTTP client.

### Endianness and protobuf

The outer WLOC framing uses **big-endian** (`network byte order`) 16-bit and 32-bit integers. The protobuf payload follows normal Protocol Buffers wire encoding: each field starts with a varint key `(field_number << 3) | wire_type`; integer fields use wire type `0` (varint); embedded messages and strings use wire type `2` (`length` varint followed by bytes). Protobuf varints are **base-128, least-significant group first**; they are not fixed-width big-endian integers.

**One-cell request body:**

| Order | Representation | Value / description |
|---|---|---|
| 1 | 2-byte big-endian signed integer | `1` |
| 2 | 2-byte big-endian length + UTF-8 bytes | `en-001_001` (10 bytes) |
| 3 | 2-byte big-endian length + UTF-8 bytes | `com.apple.locationd` (19 bytes) |
| 4 | 2-byte big-endian length + UTF-8 bytes | `18.6.2.22G100` (13 bytes) |
| 5 | 4-byte big-endian signed integer | `1` (frame type used by this PoC) |
| 6 | 4-byte big-endian signed integer | Size in **bytes** of the following protobuf message |
| 7 | `N` bytes | Top-level request protobuf |

The interpretation of the initial integer and metadata strings beyond their exact byte values is not established. An implementation can reproduce the PoC without assigning semantic names to them.

**Response body:**

| Order | Representation | Description |
|---|---|---|
| 1 | 2-byte big-endian signed integer | Observed value: `1` |
| 2 | 4-byte big-endian signed integer | Frame type; the decoder parses type `1` |
| 3 | 4-byte big-endian signed integer | Number of bytes in frame payload |
| 4 | `N` bytes | Frame protobuf |
| 5 | Repeated steps 2–4 | Additional frames, if present |

Do not treat an HTTP 200 response as an exact location result. The protobuf can report an identity with no valid coordinates.

## 3. Request protobuf: field-by-field

### Top-level fields

| Field number | Wire type | Value in a single-cell PoC request | Interpretation |
|---:|---:|---|---|
| `1` | 2 | Embedded cell identity message for GSM or UMTS | Observed RAT-specific location |
| `25` | 2 | Embedded cell identity message for LTE | Observed RAT-specific location |
| `29` | 2 | Embedded cell identity message for NR | Observed RAT-specific location |
| `3` | 0 | `0` | Meaning unknown |
| `4` | 0 | `1` | Meaning unknown |
| `31` | 0 | `1` | Meaning unknown |
| `33` | 2 | Embedded metadata message described below | Server-side function unknown |

For a one-cell lookup, the message contains **exactly one** of the RAT fields `1`, `25`, or `29`. This PoC writes fields in this order: RAT cell field, field `3`, field `4`, field `31`, field `33`. The baseline **does not contain top-level field `5`**. Do not assign names such as result limits or application identifiers to undocumented fields without external evidence.

### Embedded cell identity (request fields 1, 25, or 29)

| Field number | Wire type | Value |
|---:|---:|---|
| `1` | 0 | MCC, unsigned integer |
| `2` | 0 | MNC, unsigned integer |
| `3` | 0 | Cell identity: GSM CI, full UMTS UC-ID, LTE ECI, or NR NCI |
| `4` | 0 | GSM/UMTS LAC or LTE/NR TAC |

All four values are encoded as nonnegative varints. The working PoC sends no other embedded identity fields. The complete set of server-supported fields is unknown.

### Nested metadata (top-level field 33)

| Nested field | Wire type | Value in the baseline |
|---:|---:|---|
| `1` | 2 | UTF-8 `iPhone OS18.6.2/22G100` |
| `2` | 2 | UTF-8 `iPhone17,3` |

These are **literal test values** sent by the PoC. The program does not detect a real device, its OS, or its model.

### Complete request construction (language-independent pseudocode)

```text
function varint(n):
    require n >= 0
    output = []
    while n >= 128:
        output.append((n & 127) | 128)
        n = n >> 7
    output.append(n)
    return bytes(output)

function uint_field(number, value):
    return varint(number << 3) + varint(value)

function bytes_field(number, contents):
    return varint((number << 3) | 2) + varint(len(contents)) + contents

cell = uint_field(1, MCC) + uint_field(2, MNC)
     + uint_field(3, CELL) + uint_field(4, AREA)

metadata = bytes_field(1, utf8("iPhone OS18.6.2/22G100"))
         + bytes_field(2, utf8("iPhone17,3"))

rat_field = { GSM: 1, UMTS: 1, LTE: 25, NR: 29 }[RAT]
payload = bytes_field(rat_field, cell)
        + uint_field(3, 0) + uint_field(4, 1) + uint_field(31, 1)
        + bytes_field(33, metadata)

body = big_endian_int16(1)
for name in ["en-001_001", "com.apple.locationd", "18.6.2.22G100"]:
    name_bytes = utf8(name)
    body += big_endian_int16(len(name_bytes)) + name_bytes
body += big_endian_int32(1) + big_endian_int32(len(payload)) + payload

POST body as raw bytes to https://gs-loc.apple.com/clls/wloc
```

## 4. Request byte vectors (actual PoC output)

The following four request bodies are **complete byte vectors produced by `encode_request()`**. They are suitable for byte-for-byte checks in any programming language. Hex pairs are separated by spaces for readability; do not send the spaces.

### GSM: `262/2/350/9761` — 117 bytes

```hex
00 01 00 0a 65 6e 2d 30 30 31 5f 30 30 31 00 13 63 6f 6d 2e 61 70 70 6c 65 2e 6c 6f 63 61 74 69 6f 6e 64 00 0d 31 38 2e 36 2e 32 2e 32 32 47 31 30 30 00 00 00 01 00 00 00 3b 0a 0b 08 86 02 10 02 18 a1 4c 20 de 02 18 00 20 01 f8 01 01 8a 02 24 0a 16 69 50 68 6f 6e 65 20 4f 53 31 38 2e 36 2e 32 2f 32 32 47 31 30 30 12 0a 69 50 68 6f 6e 65 31 37 2c 33
```

### UMTS: `250/20/27811/3302913` — 120 bytes

```hex
00 01 00 0a 65 6e 2d 30 30 31 5f 30 30 31 00 13 63 6f 6d 2e 61 70 70 6c 65 2e 6c 6f 63 61 74 69 6f 6e 64 00 0d 31 38 2e 36 2e 32 2e 32 32 47 31 30 30 00 00 00 01 00 00 00 3e 0a 0e 08 fa 01 10 14 18 81 cc c9 01 20 a3 d9 01 18 00 20 01 f8 01 01 8a 02 24 0a 16 69 50 68 6f 6e 65 20 4f 53 31 38 2e 36 2e 32 2f 32 32 47 31 30 30 12 0a 69 50 68 6f 6e 65 31 37 2c 33
```

### LTE: `262/1/18000/27086850` — 121 bytes

```hex
00 01 00 0a 65 6e 2d 30 30 31 5f 30 30 31 00 13 63 6f 6d 2e 61 70 70 6c 65 2e 6c 6f 63 61 74 69 6f 6e 64 00 0d 31 38 2e 36 2e 32 2e 32 32 47 31 30 30 00 00 00 01 00 00 00 3f ca 01 0e 08 86 02 10 01 18 82 a0 f5 0c 20 d0 8c 01 18 00 20 01 f8 01 01 8a 02 24 0a 16 69 50 68 6f 6e 65 20 4f 53 31 38 2e 36 2e 32 2f 32 32 47 31 30 30 12 0a 69 50 68 6f 6e 65 31 37 2c 33
```

### NR: `234/10/149792/231735821` — 121 bytes

```hex
00 01 00 0a 65 6e 2d 30 30 31 5f 30 30 31 00 13 63 6f 6d 2e 61 70 70 6c 65 2e 6c 6f 63 61 74 69 6f 6e 64 00 0d 31 38 2e 36 2e 32 2e 32 32 47 31 30 30 00 00 00 01 00 00 00 3f ea 01 0e 08 ea 01 10 0a 18 8d 84 c0 6e 20 a0 92 09 18 00 20 01 f8 01 01 8a 02 24 0a 16 69 50 68 6f 6e 65 20 4f 53 31 38 2e 36 2e 32 2f 32 32 47 31 30 30 12 0a 69 50 68 6f 6e 65 31 37 2c 33
```

Reference request SHA-256 values are checked in `tests/test_als.py`. A new implementation should match the entire request body, not only its protobuf part.

## 5. Response protobuf: decoding rules

For each frame with type `1`, parse the frame contents as a protobuf message. Each supported cell record appears in a **repeated, length-delimited** field:

| Top-level response field | Cell RAT |
|---:|---|
| `1` | GSM or UMTS (same response tag) |
| `22` | LTE |
| `24` | NR |

GSM and UMTS cannot be distinguished from the shared response tag alone. For a single-cell request, use the requested RAT. A mixed-RAT implementation must preserve input identity and match each record to its request context; do not claim that the response explicitly declares GSM versus UMTS.

### Each embedded cell record

| Field | Wire | Decoded value / handling |
|---:|---:|---|
| `1` | 0 | MCC |
| `2` | 0 | MNC |
| `3` | 0 | Full cell identity; a decoded value of `-1` identifies an area-only entry |
| `4` | 0 | LAC or TAC |
| `5` | 2 | Nested location message |
| `6` and other fields | Varies | May be present. Their general meaning is **not specified** by this document. A compatible decoder must tolerate unknown fields. |

Decode signed two's-complement integer representations of field `3` with the correct integer width. The current PoC reads 64-bit values for GSM/UMTS and NR, and 32-bit values for LTE. Negative `-1` is used for the area-only sentinel; it is **not** a real Cell ID. Do not mistake it for unsigned `4294967295` or `18446744073709551615`.

### Location message (cell field 5)

| Field | Wire | Meaning / observed treatment |
|---:|---:|---|
| `1` | 0 | Signed 64-bit latitude integer; divide by `100000000` to get degrees |
| `2` | 0 | Signed 64-bit longitude integer; divide by `100000000` to get degrees |
| `3` | 0 | Signed integer reported accuracy in metres |
| `4`, `11`, `12`, others | Varies | Other fields observed; meanings are not established and must not be silently reinterpreted |

**Important:** The coordinates use signed **two's-complement varints**, not protobuf ZigZag (`sint64`). For negative coordinates, the wire value can occupy ten bytes. Convert the decoded unsigned varint to signed int64 **before** dividing by `1e8`. A generic ZigZag decoder will produce incorrect coordinates.

Conversion pseudocode:

```text
function to_signed64(u):
    if u >= 2^63: return u - 2^64
    return u

latitude  = to_signed64(location.field1_varint) / 100000000.0
longitude = to_signed64(location.field2_varint) / 100000000.0
accuracy  = signed_integer(location.field3_varint)

valid = latitude is in [-90,90]
     and longitude is in [-180,180]
     and accuracy >= 0
```

In observed no-location records, a location message carries out-of-range coordinate sentinel values and accuracy `-1`. A client must report `NO_LOCATION` instead of displaying a fabricated coordinate. The PoC also treats missing latitude, longitude, or accuracy as no usable location.

### Minimal decoder procedure

```text
1. Check the first two response bytes: 00 01.
2. Read one or more frames: big-endian int32 type; big-endian int32 payload_size; payload_size bytes.
3. For each type-1 frame, parse all protobuf fields.
4. For each length-delimited field 1, 22, or 24, parse one cell record.
5. Read identity fields 1..4 and location message field 5, if present.
6. Convert coordinates using signed two's-complement int64 and scale 1e8.
7. Discard invalid location values, but retain the cell identity and its NO_LOCATION state.
8. Select the requested cell by complete identity (RAT context + MCC + MNC + LAC/TAC + Cell ID).
9. If the cell has no usable coordinates, optionally use a matching area-only entry as AREA_FALLBACK.
10. Keep unrelated individual cells and area-only records separate from the requested result.
```

## 6. Observed response examples and status mapping

These are **previously observed coordinate values**, not live responses and not synthetic wire dumps. They are intended to check an implementation's decoded output.

| RAT and requested identity | Decoded latitude | Longitude | `accuracy_m` | Result |
|---|---:|---:|---:|---|
| GSM `262/2/350/9761` | 51.07746887 | 13.72264003 | 2302 | `EXACT` |
| UMTS `250/20/27811/3302913` | 55.77357864 | 37.69635772 | 7595 | `EXACT` |
| LTE `262/1/18000/27086850` | 51.08445739 | 13.76109886 | 2217 | `EXACT` |
| NR `234/10/149792/231735821` | 52.66464614 | -1.92746615 | 2063 | `EXACT` |

Observed negative cases:

| Request | Cell record | Area record | Overall interpretation |
|---|---|---|---|
| NR `240/49/100029/20125828082` | Identity returned without usable coordinates | No matching location | `NO_LOCATION` |
| NR `310/260/12517120/38277123` | Identity returned without usable coordinates | `310/260/12517120/-1`, coordinates `44.19572067, -90.64430236`, accuracy `3000` | `AREA_FALLBACK` (area location **only**) |

**Status values are defined by this PoC, not known server protocol enums:**

| PoC status | Condition |
|---|---|
| `EXACT` | Matching individual cell record **with valid coordinates** |
| `AREA_FALLBACK` | No valid matching cell location; matching area-only record has valid coordinates |
| `NO_LOCATION` | Matching cell is returned but has no valid coordinates; no matching usable area-only record |
| `MISSING` | No matching usable cell or area-only record |

An `EXACT` match means that **the identifiers match**. It does not prove an antenna's physical position or statistical confidence. The service's `accuracy_m` has not been independently calibrated by this project. Never use area-only coordinates as coordinates of a specific cell.

### Additional records

Previously observed LTE and NR single-cell responses can include **100 individual cell records (including the requested cell) and 20 area-only records**. This is an example of observed output, **not a fixed protocol limit**. Other counts occur for other queries. Results can contain several PLMNs. The position of an additional record does **not** prove it is geographically closer or more accurate.

For a future connector, match every record by the entire identity, not by its position. Preserve unknown protobuf fields, or at least tolerate them without failing the parse.

## 7. Implementation checklist for other languages

- Use HTTPS POST with an **opaque binary body**; calculate the actual Content-Length.
- Use big-endian fixed-width integers **only** in WLOC outer framing. Use protobuf varints inside messages.
- Encode the full UC-ID, ECI or NCI without truncation. Use 64-bit integers for NR identities.
- Encode request fields and metadata with the literal baseline values shown above.
- Check framing bounds and reject malformed lengths or truncated varints before allocating buffers.
- Parse protobuf by wire type. Skip unknown fields of wire types `0`, `1`, `2`, and `5` when possible.
- Convert negative coordinates from **signed two's-complement**; do **not** ZigZag-decode them.
- Distinguish a returned identity from a valid position. Keep `NO_LOCATION` and `MISSING` separate.
- Keep `cell=-1` (area) separate from individual Cell IDs. Use it only for explicitly labelled area fallback.
- Do not assume a constant number of records, specific record ordering, or a required metadata interpretation.
- Surface HTTP and decode failures separately from `NO_LOCATION`; treat any HTTP 200 as transport success only.
- Compare the generated request bytes with the four vectors above before testing a different-language client against the network.

The PoC sends **one cell per HTTP request**. This public repository does not provide batch, Wi-Fi, CDMA, database, or tracking functions. A different client can use the documented request and response messages, but unimplemented features are outside this PoC's scope.

## 8. Offline tests

```console
python -m unittest discover -s tests -v
```

The tests verify request-body SHA-256 vectors, protobuf framing and parsing, status handling, and the readable CLI output. No network connection is required for the tests. The PoC requires only Python 3.10+ and the standard library.

## License

This repository is made available under [CC0 1.0 Universal](LICENSE). The CC0 dedication applies only to the repository material that the publisher has the right to dedicate. It does not grant access to the remote service or rights to external data. This is not an official API specification.
