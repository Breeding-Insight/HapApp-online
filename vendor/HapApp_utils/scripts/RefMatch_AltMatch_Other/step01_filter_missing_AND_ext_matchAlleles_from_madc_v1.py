#!/usr/bin/env python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: step01_filter_missing_AND_ext_matchAlleles_from_madc_v1.py [-h] report
###############################################################################

"""
Extract RefMatch and AltMatch microhap alleles into a FASTA file
and assign temporary names in the report.

Retention criteria (whichever is smaller):
    - At least 10 samples, each having >= 2 reads
    - At least 5% of samples, each having >= 2 reads
"""

import argparse
import datetime
import math

def extract_RefMatch_AltMatch(data_col_index, miss_count, retained_count, alleles, threshold, line_array):
    """Extract RefMatch and AltMatch alleles based on threshold criteria."""

    # Safely parse read count columns into floats, skip non-numeric entries
    read_count_list = []
    for val in line_array[data_col_index:]:
        try:
            read_count_list.append(float(val))
        except ValueError:
            pass  # Skip DNA sequences or other non-numeric cells

    return_list = 'False'
    return_fasta = 'False'

    # Handle Ref / Alt allele IDs
    if line_array[0].endswith('Ref'):
        allele_ID = line_array[0] + '_0001'
        return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]

    elif line_array[0].endswith('Alt'):
        allele_ID = line_array[0] + '_0002'
        return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]

    else:
        # Retention check
        data_count = len([i for i in read_count_list if i >= 2])
        if data_count < threshold:
            miss_count += 1
        else:
            retained_count += 1
            alleles[line_array[0]] = alleles.get(line_array[0], 0) + 1
            allele_ID = f"{line_array[0]}_tmp_{str(alleles[line_array[0]]).zfill(4)}"
            return_fasta = f">{allele_ID}\n{line_array[2]}\n"
            return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]

    return return_list, return_fasta, miss_count, retained_count, alleles


def process_madc(report):
    """Main processing function for MADC report."""
    with open(report, encoding='utf-8-sig') as inp, \
         open(report.replace('.csv', '_match.fa'), "w") as outp_fasta, \
         open(report.replace('.csv', '_tmp_rename.csv'), 'w') as outp_report, \
         open(report.replace('.csv', '_match.log'), 'w') as outp_log:

        alleles = {}
        miss_count = retained_count = 0
        nowf = datetime.datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
        outp_log.write(f'[INFO] ## {nowf}\n')
        outp_log.write(f'[INFO] ## Processing {report}\n\n')

        data_col_index = None
        threshold = None

        for line in inp:
            line_array = line.strip().split(',')

            # Special rows prior to header
            if line_array[0] == '':
                data_col_index = line_array.count('')
                threshold = min(10, math.ceil(len(line_array[data_col_index:]) * 0.05))

            elif line_array[0] == '*':
                data_col_index = line_array.count('*')
                threshold = min(10, math.ceil(len(line_array[data_col_index:]) * 0.05))

            elif line_array[0] == 'AlleleID':
                # Set data_col_index to AFTER AlleleSequence column in header
                if 'AlleleSequence' in line_array:
                    data_col_index = line_array.index('AlleleSequence') + 1
                else:
                    data_col_index = 3
                threshold = min(10, math.ceil(len(line_array[data_col_index:]) * 0.05))

                # Check duplicate sample names in header
                check_dup_set = set([x for x in line_array[data_col_index:]
                                     if line_array[data_col_index:].count(x) > 1])
                if check_dup_set:
                    print(f"[INFO] Samples with duplicate names: {list(check_dup_set)}")
                    print(f"[INFO] Adding suffix to duplicate names starting from _1")
                    print(f"[WARNING] Remember to update these duplicate names in the passport data file!")
                    outp_log.write("# Samples with duplicate names:\n")
                    outp_log.write("# Adding suffix to duplicate names starting from _1\n")
                    outp_log.write("# Remember to update these sample names in passport data file!\n")
                    outp_log.write('\n'.join(list(check_dup_set)) + '\n\n')

                    # Rename duplicates in header
                    dup_sample_names = {}
                    for idx in range(data_col_index, len(line_array)):
                        sample_name = line_array[idx]
                        if sample_name in check_dup_set:
                            dup_sample_names[sample_name] = dup_sample_names.get(sample_name, 0) + 1
                            line_array[idx] = f"{sample_name}_{dup_sample_names[sample_name]}"
                # Write header line
                outp_report.write(','.join(line_array[:3]) + ',' + ','.join(line_array[data_col_index:]) + '\n')

            else:
                # Regular allele data rows
                return_list, return_fasta, miss_count, retained_count, alleles = \
                    extract_RefMatch_AltMatch(data_col_index, miss_count, retained_count, alleles, threshold, line_array)
                if return_list != 'False':
                    outp_report.write(','.join(return_list) + '\n')
                if return_fasta != 'False':
                    outp_fasta.write(return_fasta)

        # Summary
        print(f"[INFO] Extract RefMatch, AltMatch, and Other alleles for determining allele identity and assigning IDs")
        print(f"[INFO] Retain an allele based on whichever is smaller below:")
        print(f"[INFO]   * At least 10 samples, each having >= 2 reads")
        print(f"[INFO]   * At least 5% samples, each having >= 2 reads")
        print(f"[INFO] Number of non-Ref/Alt allele DISCARDED: {miss_count}")
        print(f"[INFO] Number of non-Ref/Alt allele RETAINED: {retained_count}")

        outp_log.write("# Extract RefMatch, AltMatch, and Other alleles for determining allele identity and assigning IDs\n")
        outp_log.write("    # Retain an allele based on whichever is smaller below:\n")
        outp_log.write("      * At least 10 samples, each having >= 2 reads\n")
        outp_log.write("      * At least 5% samples, each having >= 2 reads\n")
        outp_log.write(f"      * Number of non-Ref/Alt alleles DISCARDED: {miss_count}\n")
        outp_log.write(f"      * Number of non-Ref/Alt alleles RETAINED: {retained_count}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Extract RefMatch and AltMatch microhaps into a FASTA file and assign temp names for them in the report"
    )
    parser.add_argument('report', help='MADC report CSV file')
    args = parser.parse_args()

    process_madc(args.report)