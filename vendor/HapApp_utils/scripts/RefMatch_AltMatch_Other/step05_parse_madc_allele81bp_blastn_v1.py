#!/usr/bin/python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: step05_parse_madc_allele81bp_blastn_v1.py [-h] [--read_col READ_COL] [--cov_threshold COV_THRESHOLD] [--iden_threshold IDEN_THRESHOLD] db_allele_cnt_inp db_allele_fasta report blast seq_len
###############################################################################

def get_db_allele_fasta(db_allele_fasta, seq_len):
    db_fasta = {}
    seq_id = ''
    seq_chunks = []
    with open(db_allele_fasta) as inp:
        for raw in inp:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('>'):
                # flush previous
                if seq_id.endswith('Ref_0001') or seq_id.endswith('Alt_0002'):
                    db_fasta[seq_id] = ''.join(seq_chunks)[:seq_len]
                seq_id = line[1:]  # drop '>'
                seq_chunks = []
            else:
                seq_chunks.append(line)
        # flush last
        if seq_id.endswith('Ref_0001') or seq_id.endswith('Alt_0002'):
            db_fasta[seq_id] = ''.join(seq_chunks)[:seq_len]
    return db_fasta

 
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
    

def get_unique_blast_hits(blast):
    """
    # BLAST results of only RefMatch and AltMatch alleles
    chr3.1_078721100|RefMatch_tmp_0001 81  1   59  chr3.1_078721100|AltMatch_0006 81   1   59      59    73  94.915  3.30e-21
    [qseqid                          qlen qstart qend             sseqid        slen sstart send length qcovs pident  evalue]
    [0                                 1     2     3               4               5   6      7   8        9      10  11]

    Keep the best hit per query where locus base matches in query/subject.
    Best = max query covered length, then max percent identity, then smallest |slen-qlen|.
    Expects columns (0..11): qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue
    """
    blast_unique = {}
    with open(blast) as inp:
        for raw in inp:
            line = raw.strip()
            if not line:
                continue
            cols = line.split()
            qseqid = cols[0]
            qlen = int(cols[1])
            qstart, qend = int(cols[2]), int(cols[3])
            sseqid = cols[4]
            slen = int(cols[5])
            pident = float(cols[10])

            # Base locus strings (strip Match suffix variants)
            if 'Match' in qseqid:
                qbase = qseqid.rsplit('_', 2)[0].replace('Match', '')
                sbase = sseqid.rsplit('_', 1)[0].replace('Match', '')
            else:
                qbase = qseqid.rsplit('|', 1)[0]
                sbase = sseqid.rsplit('|', 1)[0]

            if qbase != sbase:
                continue

            qcov_len = abs(qend - qstart) + 1
            # Score tuple: higher is better for first two; for tie-breaker prefer slen closest to qlen
            score = (qcov_len, pident, -abs(slen - qlen))

            prev = blast_unique.get(qseqid)
            if prev is None:
                blast_unique[qseqid] = (score, cols)
                # score is a tuple encoding preference, e.g. (qcov_len, pident, -abs(slen - qlen)).
                # cols is the original split line for later output.
            else:
                if score > prev[0]:
                    # In Python, tuples are compared lexicographically:
                    # First compare element 0; if equal, compare element 1; if still equal, compare element 2; and so on.
                    # Because it uses strict “>”, if the score ties exactly, the first seen hit stays (stable tie handling).
                    blast_unique[qseqid] = (score, cols)

    # unwrap to {qseqid: cols}
    result = {k: v[1] for k, v in blast_unique.items()}
    print('\n[INFO] Number of unique BLAST queries written out:', len(result))
    return result
  

def determine_allele_status(db_allele_cnt, blast_unique, cov_threshold, iden_threshold):
    """
    Classify each temp allele's best BLAST hit as:
      - exact existing allele (100% cov & 100% id),
      - new allele at same locus (cov ≥ cov_threshold & id ≥ iden_threshold),
      - or discard (else).

    Returns:
      updated_db_allele_cnt, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles
    """

    print('\n[INFO] Analyze BLAST results of the non-Ref/Alt alleles in this report:')

    tmpVSdb_alleles_lut = {}   # temp -> fixed (existing or new)
    dbVStmp_alleles_lut = {}   # fixed -> [temp] (exact matches and optionally new)
    new_alleles = {}           # temp -> new fixed
    updated_db_allele_cnt = dict(db_allele_cnt)
    discarded = set()

    cov_thr = float(cov_threshold)
    id_thr = float(iden_threshold)

    def assign_new(tmp_id):
        # tmp_id: chr3.1_078721100|AltMatch_tmp_0001
        db_id_base = tmp_id.rsplit('_', 2)[0]
        updated_db_allele_cnt[db_id_base] = updated_db_allele_cnt.get(db_id_base, 0) + 1
        fixed = f"{db_id_base}_{updated_db_allele_cnt[db_id_base]:04d}"
        new_alleles[tmp_id] = fixed
        tmpVSdb_alleles_lut[tmp_id] = fixed
        return fixed

    for qid, cols in blast_unique.items():
        qlen = int(cols[1])
        qstart, qend = int(cols[2]), int(cols[3])
        sseqid = cols[4]
        pident = float(cols[10])

        qcov_len = abs(qend - qstart) + 1
        # Compare lengths to avoid recomputing percentages repeatedly
        cov_len_thr = qlen * cov_thr / 100.0
        is_exact = (qcov_len == qlen) and (pident == 100.0)
        passes_thresholds = (qcov_len >= cov_len_thr) and (pident >= id_thr)

        # Case 1: exact 100%/100% match to an existing allele (except baseline IDs)
        if is_exact:
            if not (sseqid.endswith('Ref_0001') or sseqid.endswith('Alt_0002')):
                dbVStmp_alleles_lut.setdefault(sseqid, []).append(qid)
                tmpVSdb_alleles_lut[qid] = sseqid
            else:
                print('  [WARNING] RefMatch or AltMatch matches Ref_0001 or Alt_0002, ignore:', cols)
            continue

        # Case 2: passes coverage and identity thresholds -> create a NEW allele at same locus
        elif passes_thresholds:
            # 'chr02_017916739|RefMatch_tmp_0001', '109', '1', '89', 'chr02_017916739|RefMatch_0001',
            if 'Match' in qid:
                # Derive locus bases only when needed
                tmp_base = '_'.join(qid.rsplit('_')[:-2]).replace("Match", "")
                # chr02_017916739|RefMatch_tmp_0001 -> chr02_017916739|Ref
                db_base  = '_'.join(sseqid.rsplit('_')[:-1]).replace("Match", "")
                # chr02_017916739|RefMatch_0001 -> chr02_017916739|Ref
            else:
                # "Other" alleles
                tmp_base = qid.rsplit('|', 1)[0]
                db_base  = sseqid.rsplit('|', 1)[0]

            if tmp_base == db_base:
                fixed = assign_new(qid)
                dbVStmp_alleles_lut.setdefault(fixed, []).append(qid)
            else:
                print('  [WARNING] Not aligned to the correct marker locus', cols)
                discarded.add(qid)
            continue

        # Case 3: discard (either coverage or identity failed)
        else:
            # Emit specific message when coverage passes but identity fails
            if qcov_len >= cov_len_thr and pident < id_thr:
                print(f'[INFO] >={cov_threshold}% coverage and <{iden_threshold}% identity', cols)
            discarded.add(qid)
            continue

    print('  # Number of non-Ref/Alt alleles with fixed ID assigned:', len(tmpVSdb_alleles_lut))
    print('    - Number already existing in the database:', len(tmpVSdb_alleles_lut) - len(new_alleles))
    print('    - Number of NEW alleles found in this report:', len(new_alleles))
    print('  # Number of alleles discarded because of low BLAST sequence coverage/identity:', len(discarded))

    return updated_db_allele_cnt, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles


def generate_report_with_fixed_alleleID(report, tmp_rename_report, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles, db_fasta, read_col):
    print('\n[INFO] Assign fixed allele IDs to non-Ref/Alt alleles in this report:')
    import pandas as pd
    dup = []
    dup_count = 0
    uniq_count = 0
    cols = tmp_rename_report['AlleleID']
    # tmp_rename_report: {alfalfaRep2vsXJDY1_shared_1029546|AltMatch_tmp_0001: [alfalfaRep2vsXJDY1_shared_1029546,CTTTCAGGATTGTCGATTTCCAAGCTGTTAGATTCACCACAGTGCATAATTAAAGTACTTCAAAACCACCAAATTTTAAAA,3230,0,25...]
    # dbVStmp_alleles_lut: {'chr3.1_078721100|RefMatch_0002': ['chr3.1_078721100|RefMatch_tmp_0003'] ...}
    read_start = read_col - 2
    for i in dbVStmp_alleles_lut:
        if len(dbVStmp_alleles_lut[i]) > 1:
            dup_count += len(dbVStmp_alleles_lut[i])
            uniq_count += 1
            same_allele_seq = {}
            keep_tmp_id = None
            meta_info = None
            for j in dbVStmp_alleles_lut[i]:
                if j in tmp_rename_report:
                    if keep_tmp_id is None:
                        keep_tmp_id = j
                        meta_info = tmp_rename_report[j][:read_start]
                    same_allele_seq[j] = list(map(float, tmp_rename_report[j][read_start:]))
                    dup.append([i, j] + tmp_rename_report[j])
                    del tmp_rename_report[j]
                    del tmpVSdb_alleles_lut[j]
                else:
                    print(' [INFO] This allele does not exist in temporary report: ', j)
            if same_allele_seq:
                df = pd.DataFrame.from_dict(same_allele_seq, orient='index')
                combined = meta_info + list(map(str, df.sum(axis=0)))
                dup.append([i, 'combined'] + combined)
                tmp_rename_report[keep_tmp_id] = combined
                tmpVSdb_alleles_lut[keep_tmp_id] = i
        else:
            pass


    if dup_count > 0:
        print('[WARNING] Number of non-Ref/Alt alleles having the same sequences:')
        print('   # Number of non-Ref/Alt alleles aligned to the same alleles in the database: ', dup_count)
        print('   # Number of non-Ref/Alt alleles after COMBINING those with the same sequences: ', uniq_count)

    # DAl22-7011_MADC_Report_Part1_tmp_rename_cutadapt.csv
    if 'updatedSeq' in report:
        outp_report = open(report.replace('tmp_rename_updatedSeq', 'rename_updatedSeq'), 'w')
        if len(dup) > 0:
            outp_dup = open(report.replace('tmp_rename_updatedSeq', 'rename_updatedSeq_dup'), 'w')
            outp_dup.write('AlleleID,TemporaryAlleleID,' + ','.join(tmp_rename_report['AlleleID']) + '\n')
            for i in dup:
                outp_dup.write(','.join(i) + '\n')
        else:
            pass
    else:
        outp_report = open(report.replace('tmp_rename', 'rename'), 'w')
        if len(dup) > 0:
            outp_dup = open(report.replace('tmp_rename', 'rename_dup'), 'w')
            outp_dup.write('AlleleID,TemporaryAlleleID,' + ','.join(tmp_rename_report['AlleleID']) + '\n')
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
            outp_report.write(i + ',' + ','.join(tmp_rename_report[i][:2] + tmp_rename_report[i][read_col - 2:]) + '\n')
        elif i.endswith('Ref_0001') or i.endswith('Alt_0002'):
            outp_report.write(i + ',' + tmp_rename_report[i][0] + ',' + db_fasta[i].upper() + ',' + ','.join(tmp_rename_report[i][read_col - 2:]) + '\n')
        else:
            if i in tmpVSdb_alleles_lut:
                outp_report.write(tmpVSdb_alleles_lut[i] + ',' + tmp_rename_report[i][0] + ',' + tmp_rename_report[i][1].upper() + ',' + ','.join(tmp_rename_report[i][read_col - 2:]) + '\n')
                allele_cnt += 1
            else:
                allele_discarded.append(i)

            # new_alleles = {'chr3.1_078721100|AltMatch_tmp_001': 'chr3.1_078721100|AltMatch_012', ...}
            if i in new_alleles:
                if '>'+new_alleles[i] not in new_alleles_fasta:
                    new_alleles_fasta['>' + new_alleles[i]] = tmp_rename_report[i][1].upper()
                else:
                    print('[WARNING] Allele already exists: ', i, new_alleles[i])
            else:
                pass
    outp_report.close()
    print('\n[INFO] Report with fixed allele IDs assigned to non-Ref/Alt alleles:')
    print('  # Number of non-Ref/Alt alleles assigned fixed IDs: ', allele_cnt)
    print('  # Number of non-Ref/Alt alleles discarded because of low coverage/identity or same sequences: ', len(allele_discarded), '\n\n')
    return(new_alleles_fasta)


def generate_new_db_lut(db_alleleCnt_lut_file, updated_db_allele_cnt, db_allele_cnt):
    import re
    m = re.search(r'v(\d{3})', db_alleleCnt_lut_file)
    if m:
        version = int(m.group(1)) + 1
        new_suffix = 'v' + str(version).zfill(3)
        outf = re.sub(r'v\d{3}', new_suffix, db_alleleCnt_lut_file, count=1)
    else:
        raise ValueError(f'Could not determine version from allele count LUT: {db_alleleCnt_lut_file}')
    outp_lut = open(outf, 'w')
    for i in updated_db_allele_cnt.keys():
        if i in db_allele_cnt:
            outp_lut.write('\t'.join([i, str(updated_db_allele_cnt[i]), str(db_allele_cnt[i])]) + '\n')
        else:
            outp_lut.write('\t'.join([i, str(updated_db_allele_cnt[i]), '0']) + '\n')

    outp_lut.close()
    print('[INFO] Update match allele cnt LUT with new allele counts for RefMatch and AltMatch:')
    print('  # Existing allele COUNT database: ', db_alleleCnt_lut_file)
    print('  # Updated allele COUNT database: ', outf)


def update_db_allele_fasta(db_allele_fasta, new_alleles_fasta):
    """
    # Merge new allele sequences into the existing FASTA, write an updated FASTA with a bumped version,
    and sort sequences per marker in this order:
      Ref_* (Ref_0001 first),
      Alt_* (Alt_0002 first),
      RefMatch_*,
      AltMatch_*,
      Other_*,
    with numeric suffix ascending within each class.
    # Report how many sequences are in the old and new FASTA.
    """

    import re
    import os
    def bump_version(path):
        dirname, filename = os.path.split(path)
        # Only bump the database version suffix, e.g. "_v001.fa" or "_v001_indelsAdded.fa".
        # Do not touch species/panel tokens such as "DCnutv2" earlier in the filename.
        m = re.search(r'(_v)(\d{3})(?=(_|\.))', filename, flags=re.IGNORECASE)
        if m:
            new_digits = f"{int(m.group(2)) + 1:03d}"
            new_filename = f"{filename[:m.start(2)]}{new_digits}{filename[m.end(2):]}"
        else:
            base, ext = os.path.splitext(filename)
            new_filename = f"{base}_v001{ext}"
        return os.path.join(dirname, new_filename)

    def parse_fasta(path):
        records = {}
        seq_id = None
        seq_chunks = []
        with open(path) as inp:
            for raw in inp:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    if seq_id is not None:
                        records[seq_id] = "".join(seq_chunks)
                    seq_id = line[1:]  # store without '>'
                    seq_chunks = []
                else:
                    seq_chunks.append(line)
            if seq_id is not None:
                records[seq_id] = "".join(seq_chunks)
        return records

    def normalize_new(new_dict):
        out = {}
        for k, v in new_dict.items():
            key = k[1:] if isinstance(k, str) and k.startswith(">") else k
            out[key] = v
        return out

    # Sorting: Desired class order per marker
    class_rank = {"Ref": 0, "Alt": 1, "RefMatch": 2, "AltMatch": 3, "Other": 4}
    unknown_rank = len(class_rank)

    def header_sort_key(header):
        """
        Expect 'markerID|Class_suffix', e.g., 'AGL11Exon7_000000071|Alt_0002'
        Sort by (markerID, class_rank, numeric_suffix).
        """
        try:
            marker, cls = header.split("|", 1)
        except ValueError:
            return (header, unknown_rank, float("inf"))
        parts = cls.split("_", 1)
        cls_name = parts[0]
        try:
            num = int(parts[1]) if len(parts) > 1 else float("inf")
        except ValueError:
            num = float("inf")
        rank = class_rank.get(cls_name, unknown_rank)
        return (marker, rank, num)

    # Load, normalize, merge
    existing = parse_fasta(db_allele_fasta)
    normalized_new = normalize_new(new_alleles_fasta)
    merged = dict(existing)
    merged.update(normalized_new)

    # Output path with bumped version
    outf = bump_version(db_allele_fasta)

    # Write in desired order
    with open(outf, "w") as outp:
        for header in sorted(merged.keys(), key=header_sort_key):
            outp.write(f">{header}\n{merged[header]}\n")

    # Report counts
    print("\n[INFO] Update allele SEQUENCE database (FASTA) with new non-Ref/Alt alleles:")
    print("  # Existing allele SEQUENCE database:", db_allele_fasta)
    print("    - Number of allele sequences in existing database:", len(existing))
    print("  # Updated allele SEQUENCE database:", outf)
    print("    - Number of allele sequences in the updated database:", len(merged))



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

    parser.add_argument('seq_len', type=int,
                        help='The maximum length of amplicons in MADC')

    parser.add_argument('--read_col', type=int, default=17,
                        help='Column number of read counts in the DArTag report')

    parser.add_argument('--cov_threshold', type=float, default=90.0,
                        help='Minimum coverage threshold for BLASTN hits to be considered as RefMatch/AltMatch')

    parser.add_argument('--iden_threshold', type=float, default=90.0,
                        help='Minimum identity threshold for BLASTN hits to be considered as RefMatch/AltMatch')

    args = parser.parse_args()
    
    import datetime
    now = datetime.datetime.now()
    nowf = now.strftime("%Y-%m-%d, %H:%M:%S")
    print('\n---------\n[INFO] Processed on ' + nowf)
    print('  # DArTag report with alleles assigned temporary names: ' + args.report)
    print('  # Counts of non-Ref/Alt alleles: ' + args.db_allele_cnt_inp)
    print('  # Current fasta db containing existing alleles: ' + args.db_allele_fasta)

    if args.cov_threshold is None:
        print('  # Use default coverage (90%) and identity (90%) thresholds')
    else:
        print('  # Use custom thresholds for coverage and identity:')
        print('    - Minimum coverage threshold for BLASTN hits to be retained: ', args.cov_threshold)
        print('    - Minimum identity threshold for BLASTN hits to be retained: ', args.iden_threshold)

    db_allele_cnt = get_db_allele_counts(args.db_allele_cnt_inp)
    # db_allele_cnt = {'chr3.1_078721100|RefMatch': 8, 'chr3.1_078721100|AltMatch': 11, ...}

    db_fasta = get_db_allele_fasta(args.db_allele_fasta, args.seq_len)

    tmp_rename_report = get_tmp_rename_report(args.report)
    # tmp_rename_report = {'chr3.1_078721100|RefMatch_tmp_0001': ['chr3.1_078721100', 'TCACCAACTTTCAAGTTATTGTCTTCTGCAAATATCTTCCATTCACCTGAGTACATTTCAAATCTTAGTCCTGACCGATCT', '0', '0', ...}

    blast_unique = get_unique_blast_hits(args.blast)
    outp = open(args.blast + '.unique.csv', 'w')
    for key, value in blast_unique.items():
        outp.write(','.join(value) + '\n')
    
    updated_db_allele_cnt, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles = determine_allele_status(db_allele_cnt, blast_unique, args.cov_threshold, args.iden_threshold)
    # updated_db_allele_cnt = {'chr3.1_078721100|RefMatch': 8, 'chr3.1_078721100|AltMatch': 12, ...}
    # tmpVSdb_alleles_lut = {'chr3.1_078721100|RefMatch_tmp_001': 'chr3.1_078721100|RefMatch_004', ...}
    # new_alleles = {'chr3.1_078721100|AltMatch_tmp_001': 'chr3.1_078721100|AltMatch_012', ...}

    new_alleles_fasta = generate_report_with_fixed_alleleID(args.report, tmp_rename_report, dbVStmp_alleles_lut, tmpVSdb_alleles_lut, new_alleles, db_fasta, args.read_col)
    # new_alleles_fasta = {'chr3.1_078721100|AltMatch_012': 'TCACCAACTTTCAAGTTATTGTCTTCTGCGAATGTCTTCCATCCACCTGAGAGT', ...}

    if len(new_alleles.keys()) > 0:
        generate_new_db_lut(args.db_allele_cnt_inp, updated_db_allele_cnt, db_allele_cnt)
        update_db_allele_fasta(args.db_allele_fasta, new_alleles_fasta)
    else:
        print('\n[INFO] # No new alleles found in this project\n')
