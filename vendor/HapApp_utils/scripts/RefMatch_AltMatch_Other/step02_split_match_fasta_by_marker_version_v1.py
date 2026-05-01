#!/usr/bin/env python3

import argparse
import csv
import os
import sys


SINGLE_OR_NO_VERSION_EXIT = 2


def load_marker_versions(lut):
    with open(lut, encoding="utf-8-sig", newline="") as inp:
        reader = csv.DictReader(inp)
        if "version" not in (reader.fieldnames or []):
            return None
        if "Panel_markerID" not in reader.fieldnames or "Marker_ID" not in reader.fieldnames:
            raise ValueError("LUT must contain Panel_markerID and Marker_ID columns")

        versions = {}
        for row in reader:
            version = row["version"].strip()
            if version not in {"v1", "v2"}:
                raise ValueError(f"Unexpected version for {row['Panel_markerID']}: {version!r}")
            versions[row["Panel_markerID"]] = version
            versions[row["Marker_ID"]] = version
    return versions


def read_fasta(path):
    seq_id = None
    chunks = []
    with open(path) as inp:
        for raw in inp:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if seq_id is not None:
                    yield seq_id, "".join(chunks)
                seq_id = line[1:]
                chunks = []
            else:
                chunks.append(line)
        if seq_id is not None:
            yield seq_id, "".join(chunks)


def output_paths(fasta):
    base, ext = os.path.splitext(fasta)
    if ext != ".fa":
        ext = ".fa"
    return f"{base}_v1{ext}", f"{base}_v2{ext}"


def split_fasta_by_version(lut, fasta):
    versions = load_marker_versions(lut)
    if versions is None:
        print("[INFO] LUT has no version column. Use original cutadapt workflow.")
        raise SystemExit(SINGLE_OR_NO_VERSION_EXIT)

    records = []
    counts = {"v1": 0, "v2": 0}
    missing = []
    for seq_id, seq in read_fasta(fasta):
        marker = seq_id.split("|", 1)[0]
        version = versions.get(marker)
        if version is None:
            missing.append(marker)
            continue
        records.append((version, seq_id, seq))
        counts[version] += 1

    if missing:
        uniq_missing = sorted(set(missing))
        print("[ERROR] Markers missing from LUT version column:", file=sys.stderr)
        for marker in uniq_missing[:50]:
            print(f"  {marker}", file=sys.stderr)
        if len(uniq_missing) > 50:
            print(f"  ... {len(uniq_missing) - 50} more", file=sys.stderr)
        raise SystemExit(1)

    active_versions = [version for version, count in counts.items() if count > 0]
    if len(active_versions) < 2:
        version = active_versions[0] if active_versions else "none"
        print(f"[INFO] Match FASTA contains a single marker version ({version}). Use original cutadapt workflow.")
        raise SystemExit(SINGLE_OR_NO_VERSION_EXIT)

    v1_path, v2_path = output_paths(fasta)
    with open(v1_path, "w") as out_v1, open(v2_path, "w") as out_v2:
        for version, seq_id, seq in records:
            outp = out_v1 if version == "v1" else out_v2
            outp.write(f">{seq_id}\n{seq}\n")

    print("[INFO] Split match FASTA by marker version")
    print("  # Input FASTA:", fasta)
    print("  # v1 output FASTA:", v1_path)
    print("  # v1 records:", counts["v1"])
    print("  # v2 output FASTA:", v2_path)
    print("  # v2 records:", counts["v2"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split match allele FASTA into v1 and v2 marker FASTA files")
    parser.add_argument("lut", help="SNP ID LUT containing Panel_markerID and optional version columns")
    parser.add_argument("fasta", help="RefMatch/AltMatch/Other FASTA to split")
    args = parser.parse_args()
    split_fasta_by_version(args.lut, args.fasta)
