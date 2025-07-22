#!/usr/bin/python3

def determine_allele_status(db_fasta):
    from Bio import SeqIO
    # Loop through the RefMatch and AltMatch alleles after removing adapters
    all_alleles = {}
    remove = []
    cnt = 0
    for record in SeqIO.parse(db_fasta, "fasta"):
        cnt += 1
        # Check if the sequence is already in the dictionary
        seq = str(record.seq)
        if seq in all_alleles:
            all_alleles[seq].append(record)
            remove.append(record.id)
        else:
            all_alleles[seq] = [record]
    print('# Number of microhaplotypes:', cnt)
    print('# Number of unique microhaplotypes:', len(all_alleles))
    print('# Number of microhaplotypes need removal:', len(remove))

    if len(remove) > 0:
        outp_dup = open(db_fasta + '.dup.csv', 'w')
        outp_dup.write('KeepID,Keep_seq,RemoveID,Remove_seq\n')
        for seq in all_alleles:
            dup_alleles = []
            if len(all_alleles[seq]) > 1:
                for record in all_alleles[seq]:
                    dup_alleles.append(record.id)
                    outp_dup.write(','.join([record.id, str(record.seq)]) + ',')
                outp_dup.write('\n')
            else:
                pass
        outp_dup.close()
    else:
        pass
    return(remove)

def remove_duplicate_alleles_in_db_fasta(db_fasta, remove_alleles):
    import subprocess
    cmd = 'grep -c ">" ' + db_fasta
    total_seq = subprocess.check_output(cmd, shell=True).strip().decode('ascii')
    import re
    import os
    db_fasta_array = re.split("[_|.]", db_fasta)
    version = int(db_fasta_array[-2].replace('v', '')) + 1
    new_suffix = '_v' + str(version).zfill(3)
    outf = re.sub(r'_v\d+', new_suffix, db_fasta)
    outp = open(outf, 'w')

    # Don't need to update the allele_lut.txt
    current_lut = db_fasta.replace('.fa', '_matchCnt_lut.txt')
    lut = outf.replace('.fa', '_matchCnt_lut.txt')
    cmd = 'cp ' + current_lut + ' ' + lut
    os.system(cmd)
    
    inp = open(db_fasta)
    line = inp.readline()
    remove = 'false'
    cnt = 0
    while line:
        if line.startswith('>'):
            if line[1:].strip() not in remove_alleles:
                outp.write(line)
                remove = 'false'
            else:
                remove = 'true'
                cnt += 1
        else:
            if remove == 'false':
                outp.write(line)
        line = inp.readline()
    inp.close()
    outp.close()
    print('\nRunning remove_duplicate_alleles_in_db_fasta(db_fasta, remove_alleles):')
    print('Number of alleles in the original fasta file: ', total_seq)
    print('Number of alleles removed: ', cnt)

    outp_readme = open(outf.replace('.fa', '.readme'), 'w')
    import datetime
    now = datetime.datetime.now()
    nowf = now.strftime("%Y-%m-%d, %H:%M:%S")
    outp_readme.write('## ' + nowf + '\n')
    outp_readme.write('Remove duplicate alleles and only keep one unique sequence\n\n')
    outp_readme.write('Input db fasta: ' + db_fasta + '\n')
    outp_readme.write('Output db fasta: ' + outf + '\n')
    outp_readme.write('Number of duplicate alleles removed: ' + str(len(remove_alleles)) + '\n')
    outp_readme.write('Number of alleles in the input db fasta file: ' + str(total_seq) + '\n')
    outp_readme.write('Number of alleles in the output db fasta file: ' + str(int(total_seq) - len(remove_alleles)) + '\n')


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Check whether there are duplicate allele sequences with the different allele names")

    parser.add_argument('db_fasta', help='')
    
    args = parser.parse_args()

    # Generate dictionary of duplicate alleles, with the longer alleles as keys
    remove = determine_allele_status(args.db_fasta)

    if len(remove) > 0:
        # Update db fasta file if there are duplicate alleles
        remove_duplicate_alleles_in_db_fasta(args.db_fasta, remove)
    else:
        print('# No duplicate microhaplotypes in current db:', args.db_fasta)
