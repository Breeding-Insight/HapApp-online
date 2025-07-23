#!/usr/bin/python3


def get_duplicate_alleles(dup):
    # alfalfa_allele_db_v2.fa.self.bn
    inp = open(dup)
    header = inp.readline()
    line = inp.readline()
    remove_keep_pairs = {}
    while line:
        # KeepID,Keep_seq,RemoveID,Remove_seq
        line_array = line.strip().split(',')
        remove_keep_pairs[line_array[0]] = line_array[2]
        line = inp.readline()
    inp.close()
    print('# Check if there are duplicate alleles (same sequences but different IDs) in MADC file')
    print('Running: get_duplicate_alleles(dup):')
    print('Number of duplicate allele pairs: ', len(remove_keep_pairs.keys()))
    return(remove_keep_pairs)
    

def update_madc_alleleID_and_seq_after_remove_db_duplicates(remove_keep_pairs, madc_cleaned):
    import pandas as pd
    df = pd.read_csv(madc_cleaned, index_col='AlleleID')
    drop = 'false'
    # Note that not all alelle may be in the updated MADC
    for key, value in remove_keep_pairs.items():
        if key in df.index:
            if value in df.index:
                df.loc[key] += df.loc[value]
                df.drop([value], inplace=True)
                drop = 'true'
            else:
                print(value, 'is not in the report')
    if drop == 'true':
        outf = madc_cleaned.replace('.csv', '_rmDup.csv')
        df.to_csv(outf)
    else:
        print('No duplicate microhaplotypes in the MADC\n\n')


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Check whether there are duplicate allele sequences with the different allele names")
    
    parser.add_argument('dup', help='')

    parser.add_argument('madc_cleaned', help='')
    
    args = parser.parse_args()

    # Generate dictionary of duplicate alleles, with the longer alleles or small-allele-number IDs as keys
    remove_keep_pairs = get_duplicate_alleles(args.dup)

    update_madc_alleleID_and_seq_after_remove_db_duplicates(remove_keep_pairs, args.madc_cleaned)
