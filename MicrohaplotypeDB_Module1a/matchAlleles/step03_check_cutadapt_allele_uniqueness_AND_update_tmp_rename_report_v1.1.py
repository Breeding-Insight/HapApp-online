#!/usr/bin/python3

def determine_allele_status(cutadapt_fasta):
    from Bio import SeqIO
    # Loop through the RefMatch and AltMatch alleles after removing adapters
    all_alleles = {}
    remove = []
    cnt = 0
    for record in SeqIO.parse(cutadapt_fasta, "fasta"):
        cnt += 1
        # Check if the sequence is already in the dictionary
        seq = str(record.seq)
        if seq in all_alleles:
            all_alleles[seq].append(record)
            remove.append(record.id)
        else:
            all_alleles[seq] = [record]
    
    dup_alleles_lists = []
    for seq in all_alleles:
        dup_alleles = []
        if len(all_alleles[seq]) > 1:
            for record in all_alleles[seq]:
                dup_alleles.append(record.id)
            dup_alleles_lists.append(dup_alleles)
        else:
            pass
    
    if len(dup_alleles_lists) > 0:  # Updated on 3/3/25
        outp_dup = open(cutadapt_fasta.replace('.fa', '_dup.csv'), 'w')
        outp_dup.write('Keep,Remove\n')
        for i in dup_alleles_lists:
            outp_dup.write(','.join(i) + '\n')
        outp_dup.close()
    else:
        pass
    print('  # Number of RefMatch and AltMatch microhaplotypes:', cnt)
    print('  # Number of unique RefMatch and AltMatch microhaplotypes:', len(all_alleles))
    print('  # Number of RefMatch and AltMatch microhaplotypes needing removal:', len(remove))
    return(dup_alleles_lists, remove)


def concat_duplicate_allele_readCount(tmp_rename_report, dup_alleles_lists):
    import pandas as pd
    df = pd.read_csv(tmp_rename_report)
    df = df.set_index('AlleleID')
    df = df.drop('CloneID', axis=1)
    concat_list = []
    for dup_alleles in dup_alleles_lists:
        # subset of the dataframe, only consisting duplicate alleles
        df_redun = df.loc[dup_alleles]
        df_redun_concat_dict = df_redun.sum(numeric_only=True).to_dict()
        df_redun_concat_dict['AlleleID'] = dup_alleles[0]
        concat_list.append(df_redun_concat_dict)
    
    # Convert the dict to a dataframe
    df_concat = pd.DataFrame(concat_list)
    cloneID_series = df_concat['AlleleID'].str.split('|', 1).str[0] # Add cloneID column
    df_concat.insert(0, 'CloneID', cloneID_series)
    df_concat = df_concat.set_index('AlleleID')

    print('\n# Running concat_duplicate_allele_readCount(tmp_rename_report, dup_alleles_lists_noLength, longest_alleles_list)')
    print('  # Number of unique alleles out of the duplicated ones:', len(df_concat.index))
    return(df_concat)


def put_81bp_ref_alt_allele_seq_in_dict(refAlt_81bp):
    inp = open(refAlt_81bp)
    line = inp.readline()
    refAlt_81bp_allele_dict = {}
    seq = ''
    while line:
        line = line.strip()
        if line.startswith('>'):
            if seq != '':
                refAlt_81bp_allele_dict[seq_id] = seq
            else:
                pass
            seq = ''
            seq_id = line[1:]
        else:
            seq += line
        line = inp.readline()
    # last allele
    refAlt_81bp_allele_dict[seq_id] = seq
    inp.close()
    return(refAlt_81bp_allele_dict)

def remove_duplicate_alleles_in_cutadapt_fasta(cutadapt_fasta, remove_alleles):
    import subprocess
    cmd = 'grep -c ">" ' + cutadapt_fasta
    total_seq = subprocess.check_output(cmd, shell=True).strip().decode('ascii')
    inp = open(cutadapt_fasta)
    outp = open(cutadapt_fasta.replace('.fa', '_unique.fa'), 'w')
    line = inp.readline()
    remove = 'false'
    cutadapt_uni_allele_dict = {}
    cnt = 0
    seq = ''
    while line:
        if line.startswith('>'):
            if seq != '':
                if seqID not in remove_alleles:
                    outp.write('>' + seqID + '\n')
                    outp.write(seq + '\n')
                    cutadapt_uni_allele_dict[seqID] = seq
                    cnt += 1
                else:
                    pass
            seqID = line[1:].strip()
            seq = ''
        else:
            seq += line.strip()
        line = inp.readline()
    # Last sequence
    if seqID not in remove_alleles:
        outp.write('>' + seqID + '\n')
        outp.write(seq + '\n')
        cutadapt_uni_allele_dict[seqID] = seq
        cnt += 1
    inp.close()
    outp.close()
    print('\n# Running remove_duplicate_alleles_in_cutadapt_fasta(cutadapt_fasta, remove_alleles):')
    print('  # Number of RefMatch and AltMatch in the cutadapt fasta file: ', total_seq)
    print('  # Number of RefMatch and AltMatch written to the output: ', cnt)
    return(cutadapt_uni_allele_dict)


def update_tmp_rename_report(tmp_rename_report, remove_alleles, df_concat, refAlt_81bp_allele_dict, cutadapt_uni_allele_dict):
    import pandas as pd
    df = pd.read_csv(tmp_rename_report)
    df = df.set_index('AlleleID')
    # Remove duplicated alleles
    df = df.drop(remove_alleles)
    df.update(df_concat, overwrite=True)
    df_update = df.sort_index()

    # Update allele sequence: ref and alt to 81 bp and match alleles removing adapter sequence
    for row, value in refAlt_81bp_allele_dict.items():
        if row in df_update.index:
            df_update.at[row, 'AlleleSequence'] = value

    # Update allele sequence: match alleles from cutadapt uni
    for row, value in cutadapt_uni_allele_dict.items():
        if row in df_update.index:
            df_update.at[row, 'AlleleSequence'] = value
            
    # Loop through each marker locus, and make the alleles in order of "Ref", "Alt", "RefMatch", "AltMatch"
    # !!!!!! This re-ordering will take a few minutes !!!!
    df_groupby = df_update.groupby('CloneID')
    index_ordered = []
    for cloneID, clone_df in df_groupby:
        ref = cloneID + '|Ref_0001'
        alt = cloneID + '|Alt_0002'
        index_ordered.append(ref)
        index_ordered.append(alt)
        idx_sorted = sorted(clone_df.index.to_list())
        for i in idx_sorted:
            if 'RefMatch' in i:
                index_ordered.append(i)
            else:
                pass
        
        for i in idx_sorted:
            if 'AltMatch' in i:
                index_ordered.append(i)
            else:
                pass

    df_ordered = df_update.reindex(index_ordered, axis=0)
    outf = tmp_rename_report.replace('.csv', '_updatedSeq.csv')
    df_ordered.to_csv(outf)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Check whether there are duplicate allele sequences with the different allele names")

    parser.add_argument('cutadapt_fasta', help='')

    parser.add_argument('refAlt_81bp', help='')

    parser.add_argument('tmp_rename_report', help='')
    
    args = parser.parse_args()

    # Generate a list of lists of duplicate alleles
    dup_alleles_lists, remove_alleles = determine_allele_status(args.cutadapt_fasta)
    # [['chr7.1_001382264|AltMatch_tmp_0002', 'chr7.1_001382264|AltMatch_tmp_0004', 'chr7.1_001382264|AltMatch_tmp_0003'], ...]

    if len(dup_alleles_lists) >= 1:
        # Concatenate duplicate alleles into one
        df_concat = concat_duplicate_allele_readCount(args.tmp_rename_report, dup_alleles_lists)
    
        # Update cutadapt fasta file
        cutadapt_uni_allele_dict = remove_duplicate_alleles_in_cutadapt_fasta(args.cutadapt_fasta, remove_alleles)

        # Get 81 bp ref and alt sequences
        refAlt_81bp_allele_dict = put_81bp_ref_alt_allele_seq_in_dict(args.refAlt_81bp)
        
        # Update report
        # 1. remove duplicate alleles
        # 2. add the concatenated alleles and read depth
        # 3. update allele sequences
        update_tmp_rename_report(args.tmp_rename_report, remove_alleles, df_concat, refAlt_81bp_allele_dict, cutadapt_uni_allele_dict)
    else:
        print('\n  # No duplicate microhaplotypes found in:', args.cutadapt_fasta)
