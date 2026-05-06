#!/usr/bin/env python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db01_get_reference_sfetch_keys_from_snpID_lut_v1.py [-h] [--lut LUT] [--chr_len CHR_LEN] [--flankBP FLANKBP] [--madc MADC]
###############################################################################


# Generate a key file for esl-sfetch (-Cf mode) from a marker LUT,
# optionally filtering markers by IDs listed in a MADC file.
#
# Output format (GDF per line):
#   <newname> <from> <to> <source seqname>
#
# Usage:
#   python make_sfetch_keys.py LUT.csv chr_lengths.txt 81 [--madc MADC.csv]
#
# - LUT.csv is expected to have columns including: Chr, Pos, and an ID column
#   (BI_markerID preferred; falls back to Marker_ID or Panel_markerID).
# - chr_lengths.txt is a tab-delimited file with chromosome name and length
#   (length assumed to be in the last column on each line).
# - flank length (e.g., 81) is extracted on both sides of Pos.
# - If --madc is provided, only markers whose ID appears in that MADC file
#   will be included (MADC CSV is parsed by taking the 2nd column per row,
#   skipping lines that start with '#', '*', or 'AlleleID').

import csv
import os
import sys

def get_chr_len(chr_len_file):
    """Read chromosome lengths into a dict: {chrom: int(length)}."""
    chr_len = {}
    with open(chr_len_file) as inp:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t')
            chrom = parts[0].split(' ')[0]
            try:
                length = int(parts[-1])
            except ValueError:
                # Skip lines without an integer final column
                continue
            chr_len[chrom] = length
    print(f"[INFO] Loaded {len(chr_len)} chromosome length(s) from {chr_len_file}")
    return chr_len


def get_marker_IDs(madc_path):
    """Extract marker IDs from a MADC CSV (2nd column), skipping comment/header lines."""
    ids = set()
    with open(madc_path) as inp:
        for line in inp:
            if not line or line.startswith('#') or line.startswith('*') or line.startswith('AlleleID'):
                continue
            parts = line.strip().split(',')
            if len(parts) > 1 and parts[1]:
                ids.add(parts[1])
    print(f"[INFO] Loaded {len(ids)} marker ID(s) from {madc_path}")
    return ids


def _resolve_field(fieldnames, candidates):
    """Return the first matching field from candidates (case-sensitive) or None."""
    for c in candidates:
        if c in fieldnames:
            return c
    return None

def get_sfetch_keys(lut_path, chr_len, flankBP, marker_IDs=None):
    """
    Generate sfetch key lines from LUT.
    - lut_path: CSV with columns including an ID, Chr, Pos
    - chr_len: dict of chromosome lengths
    - flankBP: int, flank size to extract on each side of Pos
    - marker_IDs: optional set of IDs to include; if None, include all
    """
    base, _ = os.path.splitext(lut_path)
    out_path = f"{base}_f{flankBP}bp_sfetchKeys.txt"
    out_count = 0

    with open(lut_path, newline='') as inp, open(out_path, 'w') as outp:
        rdr = csv.DictReader(inp)
        if rdr.fieldnames is None:
            print("[ERROR] LUT appears to have no header row.", file=sys.stderr)
            sys.exit(1)

        # Resolve necessary fields
        idcol = _resolve_field(rdr.fieldnames, ['Marker_ID', 'BI_markerID', 'Panel_markerID'])
        chrcol = _resolve_field(rdr.fieldnames, ['Chr', 'chrom', 'Chrom', 'chromosome'])
        poscol = _resolve_field(rdr.fieldnames, ['Pos', 'Position', 'pos'])

        if not all([idcol, chrcol, poscol]):
            print(f"[ERROR] Could not find required columns in LUT header. Found: {rdr.fieldnames}", file=sys.stderr)
            print("[ERROR] Need at least an ID column (BI_markerID/Marker_ID/Panel_markerID), Chr, and Pos.", file=sys.stderr)
            sys.exit(1)

        for row in rdr:
            bi_marker = (row.get(idcol) or '').strip()
            chrom = (row.get(chrcol) or '').strip()
            pos_str = (row.get(poscol) or '').strip()

            if not bi_marker or not chrom or not pos_str:
                continue
            try:
                pos = int(pos_str)
            except ValueError:
                continue

            # Optional filtering by MADC IDs
            if marker_IDs is not None and bi_marker not in marker_IDs:
                continue

            start_from = max(1, pos - flankBP)
            end_to = pos + flankBP

            # Bound by chromosome length if available
            if chrom in chr_len:
                if end_to > chr_len[chrom]:
                    end_to = chr_len[chrom]

            # GDF fields: <newname> <from> <to> <source seqname>
            outp.write('\t'.join([bi_marker, str(start_from), str(end_to), chrom]) + '\n')
            out_count += 1

    print(f"[INFO] Wrote {out_count} record(s) to {out_path}")


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate esl-sfetch key file from a marker LUT; optionally filter by marker IDs from a MADC file.")
    parser.add_argument('--lut', help='Marker LUT CSV (needs ID, Chr, Pos columns)')
    parser.add_argument('--chr_len', help='Chromosome length file (tab-delimited; last column is length)')
    parser.add_argument('--flankBP', type=int, help='Flank length to extract on each side of Pos (integer)')
    parser.add_argument('--madc', help='MADC CSV to filter marker IDs (2nd column used)')

    args = parser.parse_args()

    chr_len_map = get_chr_len(args.chr_len)
    ids_filter = get_marker_IDs(args.madc) if args.madc else None
    get_sfetch_keys(args.lut, chr_len_map, args.flankBP, marker_IDs=ids_filter)