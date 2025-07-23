#!/usr/bin/python3

def get_db_allele_fasta(db_allele_fasta):
    db_fasta = {}
    inp = open(db_allele_fasta)
    line = inp.readline()
    seq = ''
    while line:
        if line.startswith('>'):
            if seq != '':
                if seq_id not in db_fasta:
                    db_fasta[seq_id] = seq
            seq = ''
            seq_id = line.strip()[1:]
        else:
            line = line.strip()
            seq += line
        line = inp.readline()

    # Last sequence
    if seq_id not in db_fasta:
        db_fasta[seq_id] = seq
        
    inp.close()
    return(db_fasta)

 
def get_db_allele_counts(db_allele_cnt_inp):
    inp = open(db_allele_cnt_inp)
    line = inp.readline()
    db_allele_cnt = {}
    while line:
        line_array = line.strip().split('\t')
        db_allele_cnt[line_array[0]] = int(line_array[1])
        line = inp.readline()
    inp.close()
    return(db_allele_cnt)


def get_tmp_rename_report(report):
    inp = open(report)
    tmp_rename_report = {}
    # tmp_rename_report: {alfalfaRep2vsXJDY1_shared_1029546|AltMatch_tmp_0001: [alfalfaRep2vsXJDY1_shared_1029546,CTTTCAGGATTGTCGATTTCCAAGCTGTTAGATTCACCACAGTGCATAATTAAAGTACTTCAAAACCACCAAATTTTAAAA,3230,0,25...]
    line = inp.readline() # first data line
    while line:
        line_array = line.strip().split(',')
        tmp_rename_report[line_array[0]] = line_array[1:]
        line = inp.readline()
    inp.close()
    return(tmp_rename_report)
    
        
def get_unique_blast_hits(blast, db_allele_fasta):
    inp = open(blast)
    line = inp.readline()
    '''
    # BLAST results of only RefMatch and AltMatch alleles
    chr3.1_078721100|RefMatch_tmp_0001 81  1   59  chr3.1_078721100|AltMatch_0006 81   1   59      59    73  94.915  3.30e-21
    [qseqid                          qlen qstart qend             sseqid        slen sstart send length qcovs pident  evalue]
    [0                                 1     2     3               4               5   6      7   8        9      10  11]
    '''
    blast_unique = {}
    while line:
        line_array = line.strip().split()
        query_base = line_array[0].rsplit('_', 2)[0].replace('Match', '')
        subject_base = line_array[4].rsplit('_', 1)[0].replace('Match', '')

        if query_base == subject_base:
            if line_array[0] not in blast_unique:
                blast_unique[line_array[0]] = line_array
            else:
                # Compare length of coverage
                query_cov_inDict = abs(int(blast_unique[line_array[0]][3]) - int(blast_unique[line_array[0]][2])) + 1
                query_cov = abs(int(line_array[3]) - int(line_array[2])) + 1
                if query_cov > query_cov_inDict:
                    print('  # Update this query:', blast_unique[line_array[0]])
                    print('  # With this one:', line_array)
                    blast_unique[line_array[0]] = line_array
                elif query_cov == query_cov_inDict:
                    # Compare alignment identity
                    if float(line_array[10]) > float(blast_unique[line_array[0]][10]):
                        print('  # Update this query:', blast_unique[line_array[0]])
                        print('  # With this one:', line_array)
                        blast_unique[line_array[0]] = line_array
                    else:
                        pass
                else:
                    pass
        else:
            pass
        line = inp.readline()
    inp.close()
    # Sanity check
    print('  # Number of unique BLAST queries written out: ', len(blast_unique))
    return(blast_unique)
  

def determine_allele_status(db_allele_cnt, blast_unique):
    tmpVSdb_alleles_lut = {}
    # tmpVSdb_alleles_lut: {'chr3.1_078721100|RefMatch_tmp_0003': 'chr3.1_078721100|RefMatch_0002'...}
    dbVStmp_alleles_lut = {}
    # dbVStmp_alleles_lut: {'chr3.1_078721100|RefMatch_0002': ['chr3.1_078721100|RefMatch_tmp_0003'] ...}
    new_alleles = {}
    # Make a hard copy of the db because we will need to refer to the orignal db for other analysis
    updated_db_allele_cnt = dict(db_allele_cnt)
    discarded_allele_list = []
    # chr3.1_078721100|RefMatch_tmp_0001 81  1   59  chr3.1_078721100|AltMatch_0006 81   1   59      59    73  94.915  3.30e-21
    # [qseqid                          qlen qstart qend             sseqid        slen sstart send length qcovs pident  evalue]
    # [0                                 1     2     3               4               5   6      7   8        9      10  11]
    for key, line_array in blast_unique.items():
        # When query coverage is 100%
        # Note that the query coverage in BLAST output considers multiple segments of matches of a single query
        # We only consider the longest segment of the query
        q_cov = float(abs(int(line_array[3]) - int(line_array[2])) + 1) / float(line_array[1]) * 100
        if q_cov == 100.0:
            if float(line_array[10]) == 100.0:
                if not line_array[4].endswith('Ref_0001') and not line_array[4].endswith('Alt_0002'):
                    if line_array[4] not in dbVStmp_alleles_lut:
                        dbVStmp_alleles_lut[line_array[4]] = [line_array[0]]
                    else:
                        dbVStmp_alleles_lut[line_array[4]].append(line_array[0])
                    tmpVSdb_alleles_lut[line_array[0]] = line_array[4]
                else:
                    print('  RefMatch or AltMatch matches Ref_0001 or Alt_0002, ignore:', line_array)
            # New alleles: How many SNPs/mismatches are allowed in the alignment
            elif float(line_array[10]) >= 90.0 and float(line_array[10]) < 100.0:
                tmp_alleleID_base = '_'.join(line_array[0].split('_')[:-2]) # chr3.1_078721100|RefMatch_tmp_0004
                db_alleleID_base = '_'.join(line_array[4].split('_')[:-1]) # chr3.1_078721100|RefMatch_001
                # chr3.1_078721100|RefMatch
                if tmp_alleleID_base[:-9] in db_alleleID_base:
                    if tmp_alleleID_base in updated_db_allele_cnt:
                        updated_db_allele_cnt[tmp_alleleID_base] += 1
                    else:
                        updated_db_allele_cnt[tmp_alleleID_base] = 1
                    allele_ID = tmp_alleleID_base + '_' + str(updated_db_allele_cnt[tmp_alleleID_base]).zfill(4)
                    # chr3.1_078721100|RefMatch_0004
                    new_alleles[line_array[0]] = allele_ID
                    tmpVSdb_alleles_lut[line_array[0]] = allele_ID
                else:
                    print('  Not aligned to the correct marker locus', line_array)
                    if line_array[0] not in discarded_allele_list and line_array[0] not in tmpVSdb_alleles_lut:
                        discarded_allele_list.append(line_array[0])
                    else:
                        pass
            else:
                print('  100% coverage, but <90% identity', line_array)
                if line_array[0] not in discarded_allele_list and line_array[0] not in tmpVSdb_alleles_lut:
                    discarded_allele_list.append(line_array[0])
                else:
                    pass
        # When subject coverage by query sequence <100% but >=90%
        elif q_cov >= 90.0:
            if float(line_array[10]) >= 90.0:
                tmp_alleleID_base = '_'.join(line_array[0].split('_')[:-2]) # chr3.1_078721100|RefMatch_tmp_0004
                db_alleleID_base = '_'.join(line_array[4].split('_')[:-1]) # chr3.1_078721100|RefMatch_001
                if tmp_alleleID_base[:-9] in db_alleleID_base:
                    if tmp_alleleID_base in updated_db_allele_cnt:
                        updated_db_allele_cnt[tmp_alleleID_base] += 1
                    else:
                        updated_db_allele_cnt[tmp_alleleID_base] = 1
                    allele_ID = tmp_alleleID_base + '_' + str(updated_db_allele_cnt[tmp_alleleID_base]).zfill(4)
                    new_alleles[line_array[0]] = allele_ID
                    tmpVSdb_alleles_lut[line_array[0]] = allele_ID
                else:
                    print('  Not aligned to the correct marker locus', line_array)
                    if line_array[0] not in discarded_allele_list and line_array[0] not in tmpVSdb_alleles_lut:
                        discarded_allele_list.append(line_array[0])
                    else:
                        pass
            # When subject coverage by query sequence >=90% and alignment identity is <90% (Too much variations to be considered alleles)
            else:
                print('  >=90% coverage and <90% identity', line_array)
                if line_array[0] not in discarded_allele_list and line_array[0] not in tmpVSdb_alleles_lut:
                    discarded_allele_list.append(line_array[0])
                else:
                    pass

        else:
            # Alleles with <90% coverage of the subject sequence will be discarded
            if line_array[0] not in discarded_allele_list and line_array[0] not in tmpVSdb_alleles_lut:
                discarded_allele_list.append(line_array[0])
            else:
                pass

    import datetime
    now = datetime.datetime.now()
    nowf = now.strftime("%Y-%m-%d, %H:%M:%S")
    print('\n  ##', nowf)
    print('  ## Analyze BLAST results of the RefMatch and AltMatch alleles in this report:')
    print('    # Alleles from DArTag reports are different lengths')
    print('    * Number of RefMatch and AltMatch alleles with fixed ID assigned: ', len(tmpVSdb_alleles_lut))
    print('      - Number of RefMatch and AltMatch alleles already existing in the database: ', len(tmpVSdb_alleles_lut) - len(new_alleles))
    print('      - Number of NEW alleles found in this report: ', len(new_alleles.keys()))
    print('    * Number of alleles discarded because of low BLAST sequence coverage/identity: ', len(discarded_allele_list))
    return(updated_db_allele_cnt, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles)


def generate_report_with_fixed_alleleID(report, tmp_rename_report, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles, db_fasta):
    import pandas as pd
    dup = []
    dup_count = 0
    uniq_count = 0
    cols = tmp_rename_report['AlleleID']
    # tmp_rename_report: {alfalfaRep2vsXJDY1_shared_1029546|AltMatch_tmp_0001: [alfalfaRep2vsXJDY1_shared_1029546,CTTTCAGGATTGTCGATTTCCAAGCTGTTAGATTCACCACAGTGCATAATTAAAGTACTTCAAAACCACCAAATTTTAAAA,3230,0,25...]
    # dbVStmp_alleles_lut: {'chr3.1_078721100|RefMatch_0002': ['chr3.1_078721100|RefMatch_tmp_0003'] ...}
    for i in dbVStmp_alleles_lut:
        if len(dbVStmp_alleles_lut[i]) > 1:
            dup_count += len(dbVStmp_alleles_lut[i])
            uniq_count += 1
            same_allele_seq = {}
            for j in dbVStmp_alleles_lut[i]:
                if j in tmp_rename_report:
                    same_allele_seq[j] = tmp_rename_report[j][:2] + list(map(float, tmp_rename_report[j][2:]))
                    # 'AlleleID', 'CloneID', 'AlleleSequence'
                    meta_info = tmp_rename_report[j][:2]
                    dup.append([i, j] + tmp_rename_report[j])
                    del tmp_rename_report[j]
                    del tmpVSdb_alleles_lut[j]
                else:
                    print('  This allele does not exist in temporary report: ', j)
            df = pd.DataFrame.from_dict(same_allele_seq, orient='index', columns=cols)
            combined = meta_info + list(map(str, df.sum()[2:]))
            dup.append([i, 'combined'] + combined)
            tmp_rename_report[df.index[0]] = combined
        else:
            pass
    print('\n  ## Number of RefMatch and AltMatch alleles having the same sequences:')
    print('    * Number of RefMatch and AltMatch alleles aligned to the same alleles in the database: ', dup_count)
    print('    * Number of RefMatch and AltMatch alleles after COMBINING those with the same sequences: ', uniq_count)

    # DAl22-7011_MADC_Report_Part1_tmp_rename_cutadapt.csv
    if 'updatedSeq' in report:
        outp_report = open(report.replace('tmp_rename_updatedSeq', 'rename_updatedSeq'), 'w')
        if len(dup) > 0:
            outp_dup = open(report.replace('tmp_rename_updatedSeq', 'rename_updatedSeq_dup'), 'w')
            outp_dup.write('AlleleID' + ',' + ','.join(tmp_rename_report['AlleleID']) + '\n')
            for i in dup:
                outp_dup.write(','.join(i) + '\n')
        else:
            pass
    else:
        outp_report = open(report.replace('tmp_rename', 'rename'), 'w')
        if len(dup) > 0:
            outp_dup = open(report.replace('tmp_rename', 'rename_dup'), 'w')
            outp_dup.write('AlleleID' + ',' + ','.join(tmp_rename_report['AlleleID']) + '\n')
            for i in dup:
                outp_dup.write(','.join(i) + '\n')
        else:
            pass
        
    new_alleles_fasta = {}
    allele_cnt = 0
    allele_discarded = []
    #### NOTE: changed here on 2023-01-18!
    for i in tmp_rename_report:
        if i == 'AlleleID':
            outp_report.write(i + ',' + ','.join(tmp_rename_report[i]) + '\n')
        elif i.endswith('Ref_0001') or i.endswith('Alt_0002'):
            outp_report.write(i + ',' + tmp_rename_report[i][0] + ',' + db_fasta[i] + ',' + ','.join(tmp_rename_report[i][2:]) + '\n')
        else:
            if i in tmpVSdb_alleles_lut:
                outp_report.write(tmpVSdb_alleles_lut[i] + ',' + ','.join(tmp_rename_report[i]) + '\n')
                allele_cnt += 1
            else:
                allele_discarded.append(i)

            # new_alleles = {'chr3.1_078721100|AltMatch_tmp_001': 'chr3.1_078721100|AltMatch_012', ...}
            if i in new_alleles:
                if '>'+new_alleles[i] not in new_alleles_fasta:
                    new_alleles_fasta['>' + new_alleles[i]] = tmp_rename_report[i][1]
                else:
                    print('Allele already exists: ', i, new_alleles[i])
            else:
                pass
    outp_report.close()

    print('\n  ## Assign fixed allele IDs to RefMatch and AltMatch alleles in this report:')
    print('    * Number of RefMatch and AltMatch alleles assigned fixed IDs: ', allele_cnt)
    print('    * Number of RefMatch and AltMatch alleles discarded because of low coverage/identity or same sequences: ', len(allele_discarded), '\n\n')
    return(new_alleles_fasta)


def generate_new_db_lut(db_alleleCnt_lut_file, updated_db_allele_cnt, db_allele_cnt):
    import re
    # alfalfa_allele_db_v1_alleleCnt_lut.txt
    db_alleleCnt_lut_file_array = db_alleleCnt_lut_file.split('_')
    version = int(db_alleleCnt_lut_file_array[-3].replace('v', '')) + 1
    new_suffix = 'v' + str(version).zfill(3)
    outf = re.sub(r'v\d{3}', new_suffix, db_alleleCnt_lut_file)
    outp_lut = open(outf, 'w')
    for i in updated_db_allele_cnt.keys():
        if i in db_allele_cnt:
            outp_lut.write('\t'.join([i, str(updated_db_allele_cnt[i]), str(db_allele_cnt[i])]) + '\n')
        else:
            outp_lut.write('\t'.join([i, str(updated_db_allele_cnt[i]), '0']) + '\n')
    outp_lut.close()
    print('  ## Update match allele cnt LUT with new allele counts for RefMatch and AltMatch:')
    print('    * Existing allele COUNT database: ', db_alleleCnt_lut_file)
    print('    * Updated allele COUNT database: ', outf)


def update_db_allele_fasta(db_allele_fasta, new_alleles_fasta):
    import re
    import subprocess
    # alfalfa_allele_db_v1.fa
    db_allele_fasta_array = re.split("[_|.]", db_allele_fasta)
    version = int(db_allele_fasta_array[-2].replace('v', '')) + 1
    new_suffix = '_v' + str(version).zfill(3)
    outf = re.sub(r'_v\d{3}', new_suffix, db_allele_fasta)
    outp_fasta = open(outf, 'w')
    updated_db_allele_fasta = dict(new_alleles_fasta)
    inp = open(db_allele_fasta)
    line = inp.readline()
    first_seq = 'true'
    seq = ''
    while line:
        if line.startswith('>'):
            if first_seq == 'true':
                first_seq = 'false'
            else:
                if seq_id not in updated_db_allele_fasta:
                    updated_db_allele_fasta[seq_id] = seq
                else:
                    pass
            seq = ''
            seq_id = line.strip()
        else:
            line = line.strip()
            seq += line
        line = inp.readline()

    # Last sequence
    if seq_id not in updated_db_allele_fasta:
        updated_db_allele_fasta[seq_id] = seq
    else:
        pass


    for i in sorted(updated_db_allele_fasta.keys()):
        outp_fasta.write(i + '\n' + updated_db_allele_fasta[i] + '\n')
    outp_fasta.close()
    cmd = 'grep -c ">" ' + db_allele_fasta
    print('\n  ## Update allele SEQUENCE database (FASTA) with new RefMatch and AltMatch alleles:')
    print('    * Existing allele SEQUENCE database: ', db_allele_fasta)
    print('      - Number of allele sequences in existing database: ', subprocess.check_output(cmd, shell=True).decode('utf-8').strip())
    print('    * Updated allele SEQUENCE database: ', outf)
    print('      - Number of allele sequences in the updated database: ', len(updated_db_allele_fasta.keys()))
    


if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Generate stats from missing allele count")

    parser.add_argument('db_allele_cnt_inp',
                        help='Counts of RefMatch and AltMatch in allele db')

    parser.add_argument('db_allele_fasta',
                        help='Current fasta db containing existing alleles, where new alleles will be added into')

    parser.add_argument('report',
                        help='DArTag report with alleles assigned temporary names and allele sequences with adapter trimmed')

    parser.add_argument('blast',
                        help='BLASTN results of the allele sequences to the allele DB')

    args = parser.parse_args()
    
    import datetime
    now = datetime.datetime.now()
    nowf = now.strftime("%Y-%m-%d, %H:%M:%S")
    print('  ## ' + nowf + '\n')
    print('  # DArTag report with alleles assigned temporary names: ' + args.report)
    print('  # Counts of RefMatch and AltMatch: ' + args.db_allele_cnt_inp)
    print('  # Current fasta db containing existing alleles: ' + args.db_allele_fasta + '\n')

    db_allele_cnt = get_db_allele_counts(args.db_allele_cnt_inp)
    # db_allele_cnt = {'chr3.1_078721100|RefMatch': 8, 'chr3.1_078721100|AltMatch': 11, ...}

    db_fasta = get_db_allele_fasta(args.db_allele_fasta)

    tmp_rename_report = get_tmp_rename_report(args.report)
    # tmp_rename_report = {'chr3.1_078721100|RefMatch_tmp_0001': ['chr3.1_078721100', 'TCACCAACTTTCAAGTTATTGTCTTCTGCAAATATCTTCCATTCACCTGAGTACATTTCAAATCTTAGTCCTGACCGATCT', '0', '0', ...}

    blast_unique = get_unique_blast_hits(args.blast, args.db_allele_fasta)
    outp = open(args.blast + '.unique.csv', 'w')
    for key, value in blast_unique.items():
        outp.write(','.join(value) + '\n')
    
    updated_db_allele_cnt, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles = determine_allele_status(db_allele_cnt, blast_unique)
    # updated_db_allele_cnt = {'chr3.1_078721100|RefMatch': 8, 'chr3.1_078721100|AltMatch': 12, ...}
    # tmpVSdb_alleles_lut = {'chr3.1_078721100|RefMatch_tmp_001': 'chr3.1_078721100|RefMatch_004', ...}
    # new_alleles = {'chr3.1_078721100|AltMatch_tmp_001': 'chr3.1_078721100|AltMatch_012', ...}

    new_alleles_fasta = generate_report_with_fixed_alleleID(args.report, tmp_rename_report, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles, db_fasta)
    # new_alleles_fasta = {'chr3.1_078721100|AltMatch_012': 'TCACCAACTTTCAAGTTATTGTCTTCTGCGAATGTCTTCCATCCACCTGAGAGT', ...}

    if len(new_alleles.keys()) > 0:
        generate_new_db_lut(args.db_allele_cnt_inp, updated_db_allele_cnt, db_allele_cnt)
        update_db_allele_fasta(args.db_allele_fasta, new_alleles_fasta)
    else:
        print('  # No new alleles found in this project\n')
