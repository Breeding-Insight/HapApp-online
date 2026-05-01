#!/usr/bin/env python3

import argparse


def copy_fasta(inp_path, outp):
    count = 0
    with open(inp_path) as inp:
        for raw in inp:
            if raw.startswith(">"):
                count += 1
            outp.write(raw)
    return count


def concat_fastas(v1_fasta, v2_fasta, output_fasta):
    total = 0
    with open(output_fasta, "w") as outp:
        total += copy_fasta(v1_fasta, outp)
        total += copy_fasta(v2_fasta, outp)

    print("[INFO] Concatenate v1 cutadapt FASTA with v2 uncut FASTA")
    print("  # v1 FASTA:", v1_fasta)
    print("  # v2 FASTA:", v2_fasta)
    print("  # Output FASTA:", output_fasta)
    print("  # Total records:", total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Concatenate v1 cutadapt and v2 uncut FASTA files")
    parser.add_argument("v1_fasta", help="v1 FASTA after cutadapt, preferably unique if duplicate collapsing happened")
    parser.add_argument("v2_fasta", help="v2 FASTA that bypassed cutadapt")
    parser.add_argument("output_fasta", help="Concatenated output FASTA for BLAST")
    args = parser.parse_args()
    concat_fastas(args.v1_fasta, args.v2_fasta, args.output_fasta)
