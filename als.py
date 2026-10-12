#!/usr/bin/env python3
"""Minimal Apple WLOC cellular geolocation PoC (unofficial, stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://gs-loc.apple.com/clls/wloc"
MAX_BODY = 8 * 1024 * 1024
# (request field, response field); GSM/UMTS intentionally share a wire field.
RATS = {"gsm": (1, 1), "umts": (1, 1), "lte": (25, 22), "nr": (29, 24)}
RESPONSE_RATS = {1: "gsm_or_umts", 22: "lte", 24: "nr"}


def varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def field_int(tag: int, value: int) -> bytes:
    return varint(tag << 3) + varint(value)


def field_bytes(tag: int, value: bytes) -> bytes:
    return varint((tag << 3) | 2) + varint(len(value)) + value


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for index in range(10):
        if pos >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << (index * 7)
        if byte < 128:
            if index == 9 and byte > 1:
                raise ValueError("Varint exceeds uint64")
            return value, pos
    raise ValueError("Varint exceeds ten bytes")


def protobuf_fields(data: bytes):
    pos = 0
    while pos < len(data):
        key, pos = read_varint(data, pos)
        tag, wire = key >> 3, key & 7
        if not tag:
            raise ValueError("Protobuf field 0 is invalid")
        if wire == 0:
            value, pos = read_varint(data, pos)
        elif wire == 2:
            length, pos = read_varint(data, pos)
            if length > MAX_BODY or length > len(data) - pos:
                raise ValueError("Invalid protobuf length")
            value = data[pos:pos + length]
            pos += length
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            if pos + length > len(data):
                raise ValueError("Truncated fixed-width protobuf field")
            value = data[pos:pos + length]
            pos += length
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        yield tag, wire, value


def signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def get_int(parts, tag: int, bits: int = 32) -> int | None:
    return next((signed(v, bits) for t, w, v in parts if t == tag and w == 0), None)


def validate(rat: str, mcc: int, mnc: int, area: int, cell: int) -> None:
    if rat not in RATS:
        raise ValueError(f"Unsupported RAT {rat!r}; choose gsm, umts, lte, nr")
    if not 1 <= mcc <= 999 or not 0 <= mnc <= 999:
        raise ValueError("MCC must be 1..999, MNC must be 0..999")
    area_max = (1 << 24) - 1 if rat == "nr" else 65535
    if not 0 <= area <= area_max:
        raise ValueError(f"Invalid {rat.upper()} area: expected 0..{area_max}")
    cell_bits = {"gsm": 16, "umts": 28, "lte": 28, "nr": 36}[rat]
    if not 0 <= cell < (1 << cell_bits):
        raise ValueError(f"Invalid {rat.upper()} Cell ID: expected unsigned {cell_bits}-bit ID")


def encode_request(rat: str, mcc: int, mnc: int, area: int, cell: int) -> bytes:
    """Reproduce the exact established single-cell baseline wire format."""
    validate(rat, mcc, mnc, area, cell)
    cell_message = (field_int(1, mcc) + field_int(2, mnc) +
                    field_int(3, cell) + field_int(4, area))
    device_metadata = (field_bytes(1, b"iPhone OS18.6.2/22G100") +
                       field_bytes(2, b"iPhone17,3"))
    payload = (field_bytes(RATS[rat][0], cell_message) +
               field_int(3, 0) + field_int(4, 1) +
               field_int(31, 1) + field_bytes(33, device_metadata))
    names = ("en-001_001", "com.apple.locationd", "18.6.2.22G100")
    preamble = struct.pack("!h", 1) + b"".join(
        struct.pack("!h", len(b)) + b for b in (x.encode("utf-8") for x in names)
    )
    return preamble + struct.pack("!ii", 1, len(payload)) + payload


def decode_location(data: bytes) -> dict:
    parts = list(protobuf_fields(data))
    lat = get_int(parts, 1, 64)
    lon = get_int(parts, 2, 64)
    accuracy = get_int(parts, 3)
    usable = (lat is not None and lon is not None and accuracy is not None and
              -90 * 10**8 <= lat <= 90 * 10**8 and
              -180 * 10**8 <= lon <= 180 * 10**8 and accuracy >= 0)
    return {"latitude": lat / 1e8 if usable else None,
            "longitude": lon / 1e8 if usable else None,
            "accuracy_m": accuracy, "has_location": usable,
            "unknown_location_fields": {str(t): v for t, w, v in parts
                                        if w == 0 and t not in (1, 2, 3)}}


def decode_cell(tag: int, data: bytes) -> dict:
    parts = list(protobuf_fields(data))
    location = next((v for t, w, v in parts if t == 5 and w == 2), None)
    result = {"response_rat": RESPONSE_RATS[tag],
              "mcc": get_int(parts, 1), "mnc": get_int(parts, 2),
              "area": get_int(parts, 4),
              "cell": get_int(parts, 3, 64 if tag in (1, 24) else 32)}
    result.update(decode_location(location) if location is not None else
                  {"latitude": None, "longitude": None, "accuracy_m": None,
                   "has_location": False, "unknown_location_fields": {}})
    return result


def decode_response(raw: bytes) -> list[dict]:
    if len(raw) < 2 or struct.unpack_from("!h", raw)[0] != 1:
        raise ValueError("Invalid WLOC response preamble/version")
    offset = 2
    records = []
    frames = 0
    while offset < len(raw):
        if len(raw) - offset < 8:
            raise ValueError("Truncated WLOC frame")
        typ, size = struct.unpack_from("!ii", raw, offset)
        offset += 8
        if size < 0 or size > MAX_BODY or size > len(raw) - offset:
            raise ValueError("Invalid WLOC frame length")
        frame = raw[offset:offset + size]
        offset += size
        frames += 1
        if typ == 1:
            for tag, wire, value in protobuf_fields(frame):
                if tag in RESPONSE_RATS and wire == 2:
                    records.append(decode_cell(tag, value))
    if not frames:
        raise ValueError("Missing WLOC response frames")
    return records


def interpret(records: list[dict], rat: str, mcc: int, mnc: int, area: int, cell: int) -> dict:
    expected = "gsm_or_umts" if rat in ("gsm", "umts") else rat
    exact = [r for r in records if r["response_rat"] == expected and
             (r["mcc"], r["mnc"], r["area"], r["cell"]) ==
             (mcc, mnc, area, cell)]
    areas = [r for r in records if r["response_rat"] == expected and
             (r["mcc"], r["mnc"], r["area"], r["cell"]) ==
             (mcc, mnc, area, -1)]
    exact_location = next((r for r in exact if r["has_location"]), None)
    area_location = next((r for r in areas if r["has_location"]), None)
    status = ("EXACT" if exact_location else "AREA_FALLBACK" if area_location
              else "NO_LOCATION" if exact else "MISSING")
    extras = [r for r in records if r["cell"] is not None and r["cell"] >= 0 and
              r not in exact]
    return {"query": {"rat": rat, "mcc": mcc, "mnc": mnc, "area": area, "cell": cell},
            "status": status,
            "cell_result": exact_location or (exact[0] if exact else None),
            "area_fallback": area_location,
            "additional_cells": len(extras),
            "area_only_records": sum(r["cell"] == -1 for r in records),
            "records_total": len(records)}


def lookup(rat: str, mcc: int, mnc: int, area: int, cell: int,
           timeout: float = 12, include_records: bool = False) -> dict:
    body = encode_request(rat, mcc, mnc, area, cell)
    headers = {
        "User-Agent": "locationd/2964.0.8 CFNetwork/3826.600.41 Darwin/24.6.0",
        "Accept": "*/*", "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    request = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = response.status
        raw = response.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("WLOC response exceeds maximum allowed size")
    if status != 200:
        raise ValueError(f"Unexpected HTTP status {status}")
    records = decode_response(raw)
    result = interpret(records, rat, mcc, mnc, area, cell)
    result.update({"http_status": status, "response_bytes": len(raw),
                   "response_sha256": hashlib.sha256(raw).hexdigest()})
    if include_records:
        result["records"] = records
    return result


def format_record(record: dict, rat: str) -> str:
    """Format one decoded WLOC record for an interactive PoC session."""
    location = (f"{record['latitude']:.8f},{record['longitude']:.8f}"
                if record['has_location'] else "unavailable")
    return (f"{rat.upper():5s} {record['mcc']}/{record['mnc']}/"
            f"{record['area']}/{record['cell']} lat,lon={location} "
            f"accuracy_m={record['accuracy_m']}")


def display_result(result: dict, include_records: bool = False) -> None:
    """Human-readable terminal report. No files are created."""
    query = result['query']
    rat = query['rat']
    identity = f"{query['mcc']}/{query['mnc']}/{query['area']}/{query['cell']}"
    status = result['status']
    cell_record = result['cell_result']
    area_record = result['area_fallback']
    print(f"=== APPLE WLOC {rat.upper()} {identity} ===")
    print(f"HTTP: {result['http_status']} | RESPONSE: {result['response_bytes']} bytes | "
          f"RECORDS: {result['records_total']}")
    print(f"LOOKUP: {status}")
    print("REQUESTED CELL:")
    if cell_record is not None:
        print('  ' + format_record(cell_record, rat))
        if not cell_record['has_location']:
            print('  [NO COORDINATES FOR THE REQUESTED CELL]')
    else:
        print('  not returned')
    print(f"ADDITIONAL CELLS ({result['additional_cells']}):")
    records = result.get('records', [])
    extras = [r for r in records if r['cell'] is not None and r['cell'] >= 0
              and (r['response_rat'], r['mcc'], r['mnc'], r['area'], r['cell']) !=
              (('gsm_or_umts' if rat in ('gsm', 'umts') else rat),
               query['mcc'], query['mnc'], query['area'], query['cell'])]
    if include_records and extras:
        for row in extras:
            print('  ' + format_record(row, rat))
    else:
        print('  (use --all-records to display)' if result['additional_cells'] else '  none')
    print(f"AREA-ONLY LAC/TAC RECORDS ({result['area_only_records']}):")
    areas = [r for r in records if r['cell'] == -1]
    if include_records and areas:
        for row in areas:
            print('  ' + format_record(row, rat))
    else:
        print('  (use --all-records to display)' if result['area_only_records'] else '  none')
    if area_record:
        print('MATCHED AREA FALLBACK (NOT A CELL LOCATION):')
        print('  ' + format_record(area_record, rat))
    print(f"RESPONSE_SHA256: {result['response_sha256']}")
    print('NOTE: Area-only records are not individual cell locations.')
    print(f"SUMMARY: {rat.upper()} {identity} {status}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Unofficial Apple WLOC cellular lookup PoC")
    parser.add_argument("rat", choices=RATS)
    parser.add_argument("mcc", type=int)
    parser.add_argument("mnc", type=int)
    parser.add_argument("area", type=int, help="LAC (GSM/UMTS) or TAC (LTE/NR)")
    parser.add_argument("cell", type=int, help="CID / UMTS UC-ID / LTE ECI / NR NCI")
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--all-records", action="store_true", help="Print all returned cells and areas")
    parser.add_argument("--json", action="store_true", help="Optional decoded JSON for connector development")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be in (0,120] seconds")
    try:
        result = lookup(args.rat, args.mcc, args.mnc, args.area, args.cell,
                        args.timeout, args.all_records)
    except (ValueError, urllib.error.URLError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        display_result(result, args.all_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
