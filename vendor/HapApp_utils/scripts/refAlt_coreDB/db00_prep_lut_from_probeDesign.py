#!/usr/bin/env python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db00_prep_lut_from_probeDesign.py [-h] [--madc MADC] probe
###############################################################################
"""
Prepare a SNP‑lookup table (LUT) from a probe design file.

Features:
• Optional MADC file – if omitted, LUT is built from all markers in the probe.
• APP’s output file automatically named: <probe>_snpID_lut.csv
• Simplified argparse at the bottom of this file.
• Small, well‑documented functions for easy debugging.
• Progress messages prefix with [INFO].
"""

from typing import Optional


# ----------------------------------------------------------------------
def get_panel_marker_ids(madc_path, probe):
    """
    Read a MADC report and return a list of panel marker IDs.
    Lines beginning with '#', '*', or the header 'AlleleID' are ignored.
    """
    # Generate a dictionary of panel marker IDs as keys, chr_pos as values
    markerID_lut = {}
    delimiter = '\t' if probe.endswith('.txt') else ','
    with open(probe, 'r', encoding='utf-8') as fp:
        for line in fp:
            if line.startswith('MarkerName') or line.startswith('Marker Name'):
                continue

            line_array = line.strip().split(delimiter)
            chr_pos = f"{line_array[3].strip()}_{line_array[4].strip().zfill(9)}"
            markerID_lut[line_array[0]] = chr_pos


    panel_markers = {}
    # Chr11_066551564 ['Chr11_66551564', 109, 'Chr11_66551564_112to113cM_dentatamollissimaancestry', 81]
    with open(madc_path, 'r', encoding='utf-8') as fp:
        for line in fp:
            if line.startswith('#') or line.startswith('*') or line.startswith('AlleleID'):
                continue

            line_array = line.strip().split(',')
            if line_array[0].endswith('|Ref'):
                if line_array[1] in markerID_lut:
                    chr_pos = markerID_lut[line_array[1]]
                    if chr_pos in panel_markers:
                        panel_markers[chr_pos].append(line_array[1])
                        panel_markers[chr_pos].append(str(len(line_array[2])))
                    else:
                        panel_markers[chr_pos] = [line_array[1], str(len(line_array[2]))]
                else:
                    print(f"[INFO] {line_array[1]} not in probe design file")

    madc_markers_rmDup = []
    outp = open(probe.replace('.txt', '_dup.csv').replace('.csv', '_dup.csv'), 'w')
    dup_cnt = 0
    for key, value in panel_markers.items():
        if len(value) > 2:
            print("[INFO] Duplicate markers with the same anchor variant: ", key, value)
            outp.write(key + ", " + ", ".join(value) + "\n")
            dup_cnt += 1
            index = 0
            max_len_seq = 0

            while index < len(value) - 1:
                if int(value[index + 1]) > max_len_seq:
                    max_len_seq = int(value[index + 1])
                    max_len_seq_ID = value[index]
                else:
                    pass
                index += 2
            madc_markers_rmDup.append(max_len_seq_ID)
        else:
            madc_markers_rmDup.append(value[0])
    outp.close()
    print('[INFO] Number of anchor variants with different marker names (Duplicate markers):', dup_cnt)
    print('[INFO] Number of unique markers in the panel:', len(panel_markers))
    return madc_markers_rmDup


# ----------------------------------------------------------------------
def write_lut_header(out_fp: str, delimiter: str):
    """Write the LUT header, specialized for the expected CSV format."""
    header = [ "Panel_markerID", "Marker_ID", "Chr",
               "Pos", "Ref", "Alt", "Type",
               "Indel_pos", "Priority", "Note" ]
    with open(out_fp, 'w', encoding='utf-8') as fp:
        fp.write(delimiter.join(header) + '\n')
    return out_fp


# ----------------------------------------------------------------------
def prepare_lut(probe_path: str, panel_markers: Optional[list]) -> int:
    """
    Build the LUT from <probe_path>.

    Returns the number of entries written.
    """
    out_path = probe_path.replace('.txt', '_snpID_lut.csv').replace('.csv', '_snpID_lut.csv')
    delimiter = '\t' if probe_path.endswith('.txt') else ','

    write_lut_header(out_path, delimiter)

    entry_count = 0
    with open(probe_path, 'r', encoding='utf-8-sig') as probe_fp,\
         open(out_path, 'a', encoding='utf-8') as out_fp:
        for line in probe_fp:
            if line.startswith('Marker Name') or line.startswith('#'):
                continue

            parts = line.strip().split(delimiter)
            marker_id = parts[0].strip()
            if panel_markers is not None and marker_id not in panel_markers:
                continue

            # Build Bi‑marker and positional fields
            chrom = parts[3].strip()
            pos = parts[4].strip()
            bi_marker_id = f"{chrom}_{pos.zfill(9)}"


            # Variant definition: REF/ALT
            var_def   = parts[5].strip().strip('[]').split('/')
            ref, alt  = var_def[0].strip(), var_def[1].strip()

            var_type = parts[6].strip()
            priority = parts[7].strip() if len(parts) > 7 else ''
            note     = parts[8].strip() if len(parts) > 8 else ''

            indel_pos = 'check_indel_pos' if 'indel' in var_type.lower() else ''

            # Write the row
            out_fp.write(
                delimiter.join([marker_id, bi_marker_id, chrom,
                                pos, ref, alt, var_type,
                                indel_pos, priority, note]) + '\n'
            )
            entry_count += 1

    print(f'[INFO] Prepared LUT "{out_path}" with {entry_count} entries')
    return entry_count


# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build a SNP LUT from probe design file")
    parser.add_argument("--madc", "-m",
        help="Raw MADC report (optional). If omitted, all markers in probe are used.")

    parser.add_argument("probe", help="Probe design file (.txt or .csv)")

    args = parser.parse_args()

    panel_markers = get_panel_marker_ids(args.madc, args.probe) if args.madc else None

    prepare_lut(args.probe, panel_markers)