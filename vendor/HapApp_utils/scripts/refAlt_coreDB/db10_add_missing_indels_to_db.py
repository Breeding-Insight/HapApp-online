#!/usr/bin/env python3

###############################################################################
###    @author: Alex Sandercock
###  @email: aherranssanderco@ufl.edu
###  @date: 04/01/2026
###  Usage: db10_add_missing_indels_to_db.py --lut LUT --probe PROBE \
###         --amplicons AMPLICONS --input_fasta INPUT_FASTA \
###         --input_matchcnt INPUT_MATCHCNT --output_fasta OUTPUT_FASTA \
###         --output_matchcnt OUTPUT_MATCHCNT --ref_len REF_LEN
###############################################################################

import argparse
import csv
import re
import shutil
from collections import OrderedDict


def read_fasta(fasta_path):
    records = OrderedDict()
    header = None
    seq_chunks = []
    with open(fasta_path, 'r', encoding='utf-8') as inp:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if header is not None:
                    records[header] = ''.join(seq_chunks).upper()
                header = line[1:].split()[0]
                seq_chunks = []
            else:
                seq_chunks.append(line)
    if header is not None:
        records[header] = ''.join(seq_chunks).upper()
    return records


def write_fasta(records, fasta_path):
    with open(fasta_path, 'w', encoding='utf-8') as outp:
        for header, seq in records.items():
            outp.write(f'>{header}\n{seq}\n')


def reverse_complement(seq):
    return seq.translate(str.maketrans('ACGTNacgtn', 'TGCANtgcan'))[::-1].upper()


def parse_probe_reader(probe_path):
    probe_fp = open(probe_path, 'r', encoding='utf-8-sig', newline='')
    sample = probe_fp.read(4096)
    probe_fp.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',\t')
    except csv.Error:
        dialect = csv.excel_tab if probe_path.endswith('.txt') else csv.excel
    reader = csv.DictReader(probe_fp, dialect=dialect)
    return probe_fp, reader


def get_indel_markers(lut_path):
    indels = OrderedDict()
    with open(lut_path, 'r', encoding='utf-8', newline='') as inp:
        reader = csv.DictReader(inp)
        for row in reader:
            if (row.get('Type') or '').strip().lower() != 'indel':
                continue
            marker_id = (row.get('Marker_ID') or '').strip()
            panel_marker = (row.get('Panel_markerID') or '').strip()
            if marker_id and panel_marker:
                indels[marker_id] = panel_marker
    return indels


def get_probe_rows(probe_path):
    probe_rows = {}
    probe_fp, reader = parse_probe_reader(probe_path)
    try:
        for row in reader:
            marker_name = (row.get('MarkerName') or row.get('Marker Name') or '').strip()
            if marker_name:
                probe_rows[marker_name] = row
    finally:
        probe_fp.close()
    return probe_rows


def expand_target_sequence(target_sequence):
    match = re.match(r'^(.*)\[([^/\]]+)/([^/\]]+)\](.*)$', target_sequence.strip())
    if not match:
        raise ValueError(f'Could not parse TargetSequence: {target_sequence}')
    left_flank, ref_value, alt_value, right_flank = match.groups()
    ref_seq = '' if ref_value == '-' else ref_value.upper()
    alt_seq = '' if alt_value == '-' else alt_value.upper()
    return {
        'Ref': (left_flank + ref_seq + right_flank).upper(),
        'Alt': (left_flank + alt_seq + right_flank).upper(),
    }


def normalize_indel_sequence(marker_id, allele_label, amplicon_seq, probe_row, ref_len):
    target_sequence = (probe_row.get('TargetSequence') or '').strip()
    if not target_sequence:
        raise ValueError(f'Missing TargetSequence for {marker_id}')

    allele_key = 'Ref' if allele_label.startswith('Ref') else 'Alt'
    expanded = expand_target_sequence(target_sequence)[allele_key]
    candidates = [expanded, reverse_complement(expanded)]

    prefix_matches = [candidate for candidate in candidates if candidate.startswith(amplicon_seq)]
    if len(prefix_matches) == 1:
        normalized = prefix_matches[0][:ref_len]
    else:
        contained = []
        for candidate in candidates:
            start = candidate.find(amplicon_seq)
            if start >= 0 and start + ref_len <= len(candidate):
                contained.append((candidate, start))
        if len(contained) != 1:
            raise ValueError(
                f'Could not uniquely extend {marker_id}|{allele_label}: '
                f'{len(prefix_matches)} prefix matches, {len(contained)} contained matches'
            )
        candidate, start = contained[0]
        normalized = candidate[start:start + ref_len]

    if len(normalized) != ref_len:
        raise ValueError(
            f'Normalized sequence length for {marker_id}|{allele_label} is {len(normalized)}, expected {ref_len}'
        )
    if not normalized.startswith(amplicon_seq):
        raise ValueError(
            f'Normalized sequence for {marker_id}|{allele_label} does not preserve the step-6 amplicon prefix'
        )
    return normalized


def main():
    parser = argparse.ArgumentParser(
        description='Add any missing indel baseline alleles to the finalized core DB FASTA.'
    )
    parser.add_argument('--lut', required=True, help='snpID LUT built from the probe design file')
    parser.add_argument('--probe', required=True, help='Probe design file')
    parser.add_argument('--amplicons', required=True, help='Step-6 Ref/Alt amplicon FASTA from the MADC report')
    parser.add_argument('--input_fasta', required=True, help='Finalized pre-indel allele DB FASTA')
    parser.add_argument('--input_matchcnt', required=True, help='Finalized pre-indel match-count LUT')
    parser.add_argument('--output_fasta', required=True, help='Output FASTA path')
    parser.add_argument('--output_matchcnt', required=True, help='Output match-count LUT path')
    parser.add_argument('--ref_len', required=True, type=int, help='Final allele length used for the core DB')
    args = parser.parse_args()

    indel_markers = get_indel_markers(args.lut)
    probe_rows = get_probe_rows(args.probe)
    amplicons = read_fasta(args.amplicons)
    fasta_records = read_fasta(args.input_fasta)
    output_records = OrderedDict(fasta_records)

    added_headers = []
    for marker_id, panel_marker in indel_markers.items():
        probe_row = probe_rows.get(panel_marker)
        if probe_row is None:
            raise ValueError(f'Probe row not found for indel marker {marker_id} ({panel_marker})')

        for allele_label in ('Ref_0001', 'Alt_0002'):
            header = f'{marker_id}|{allele_label}'
            if header in output_records:
                continue

            amplicon_seq = amplicons.get(header)
            if amplicon_seq is None:
                raise ValueError(f'Amplicon sequence not found for missing indel allele {header}')

            normalized_seq = normalize_indel_sequence(
                marker_id, allele_label, amplicon_seq, probe_row, args.ref_len
            )
            output_records[header] = normalized_seq
            added_headers.append(header)

    write_fasta(output_records, args.output_fasta)
    shutil.copyfile(args.input_matchcnt, args.output_matchcnt)

    print(f'[INFO] Number of indel loci in LUT: {len(indel_markers)}')
    print(f'[INFO] Missing indel baseline alleles added: {len(added_headers)}')
    if added_headers:
        print('[INFO] Added headers:', added_headers)
    else:
        print('[INFO] No missing indel baseline alleles were found')
    print(f'[INFO] Output FASTA: {args.output_fasta}')
    print(f'[INFO] Output match-count LUT: {args.output_matchcnt}')


if __name__ == '__main__':
    main()
