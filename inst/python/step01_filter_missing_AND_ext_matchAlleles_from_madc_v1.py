#!/usr/bin/python3

'''
# Only extract RefMatch and AltMatch alleles for determining allele identity and assigning existing IDs or new IDs
# Retain a microhap based on whichever is smaller below:
    # At least 10 samples, each having a minimum of 2 reads 
    # At least 5% samples, each having a minimum of 2 reads
'''

def extract_RefMatch_AltMatch(data_col_index, miss_count, retained_count, alleles, threshold, line_array):
    read_count_list = list(map(float, line_array[data_col_index:]))
    return_list = 'False'
    return_fasta = 'False'
    # Processing all microhaps    
    if line_array[0].endswith('Ref'):
        allele_ID = line_array[0] + '_0001'
        return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]
    elif line_array[0].endswith('Alt'):
        allele_ID = line_array[0] + '_0002'
        return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]
    
    # Only put the RefMatch and AltMatch allele sequences to the output
    elif line_array[0].endswith('RefMatch') or line_array[0].endswith('AltMatch'):
        # Retain a microhap based on whichever is smaller below:
        # At least 10 samples, each having a minimum of 2 reads 
        # At least 5% samples, each having a minimum of 2 reads
        data_count = len([i for i in read_count_list if i >= 2])
        if data_count < threshold:
            miss_count += 1
        else:
            retained_count += 1
            if line_array[0] in alleles:
                alleles[line_array[0]] += 1
            else:
                alleles[line_array[0]] = 1
            allele_ID = line_array[0] + "_tmp_" + str(alleles[line_array[0]]).zfill(4)
            return_fasta = '>' + allele_ID + '\n' + line_array[2] + '\n'
            return_list = [allele_ID] + line_array[1:3] + line_array[data_col_index:]
    else:
        pass
        # Ignore 'Other' alleles     
    return(return_list, return_fasta, miss_count, retained_count, alleles)
        
        
def process_madc(report):
    inp = open(report, encoding='utf-8-sig')
    line = inp.readline()
    outp_fasta = open(report.replace('.csv', '_match.fa'), "w")
    outp_report = open(report.replace('.csv', '_tmp_rename.csv'), 'w')
    outp_log = open(report.replace('.csv', '_match.log'), 'w')
    alleles = {}
    miss_count = retained_count = 0
    import datetime
    now = datetime.datetime.now()
    nowf = now.strftime("%Y-%m-%d, %H:%M:%S")
    outp_log.write('## ' + nowf + '\n')
    outp_log.write('## Processing ' + report + '\n\n')
    while line:
        line_array = line.strip().split(',')
        if line_array[0] == '':
            data_col_index = line_array.count('')
            # Determine which criterium to use to retain microhaps
            import math
            if len(line_array[data_col_index:]) * 0.05 < 10:
                threshold = math.ceil(len(line_array[data_col_index:]) * 0.05)
            else:
                threshold = 10
        elif line_array[0] == '*':
            data_col_index = line_array.count('*')
            import math
            if len(line_array[data_col_index:]) * 0.05 < 10:
                threshold = math.ceil(len(line_array[data_col_index:]) * 0.05)
            else:
                threshold = 10
        elif line_array[0] == 'AlleleID':
            # Check if all sample names are unique
            check_dup_set = set([x for x in line_array[data_col_index:] if line_array[data_col_index:].count(x) > 1])
            if len(check_dup_set) != 0:
                print('  # Samples with duplicate names:', list(check_dup_set))
                print('    # Adding suffix to duplicate names starting from _1')
                print('    # Remember to update these sample names in passport data file!')

                outp_log.write('# Samples with duplicate names:\n')
                outp_log.write('# Adding suffix to duplicate names starting from _1\n')
                outp_log.write('# Remember to update these sample names in passport data file!\n')
                outp_log.write('\n'.join(list(check_dup_set)) + '\n\n')
                dup_sample_names = {}
                index = data_col_index
                while index < len(line_array):
                    if line_array[index] in list(check_dup_set):
                        if line_array[index] not in dup_sample_names:
                            dup_sample_names[line_array[index]] = 1
                            line_array[index] = line_array[index] + '_1'
                        else:
                            dup_sample_names[line_array[index]] += 1
                            line_array[index] = line_array[index] + '_' + str(dup_sample_names[line_array[index]])
                    else:
                        pass
                    index += 1
            else:
                pass
            # 'AlleleID', 'CloneID', 'AlleleSequence'
            outp_report.write(','.join(line_array[:3]) + ',' + ','.join(line_array[data_col_index:]) + '\n') # Write out the header
        else:
            '''
            VaccDscaff11_001337505|Ref
            VaccDscaff11_001337505|Alt
            VaccDscaff11_001337505|RefMatch
            VaccDscaff11_001337505|AltMatch
            '''
            return_list, return_fasta, miss_count, retained_count, alleles = extract_RefMatch_AltMatch(data_col_index, miss_count, retained_count, alleles, threshold, line_array)
            if return_list != 'False':
                outp_report.write(','.join(return_list) + '\n')
            if return_fasta != 'False':
                outp_fasta.write(return_fasta)
        line = inp.readline()
    
    print('  # Only extract RefMatch and AltMatch alleles for determining allele identity and assigning existing IDs or new IDs')
    print('    # Retain a RefMatch or AltMatch based on whichever is smaller below:')
    print('      * At least 10 samples, each having a minimum of 2 reads') 
    print('      * At least 5% samples, each having a minimum of 2 reads\n')
    print('      * Number of RefMatch and AltMatch alleles DISCARDED: ', miss_count)
    print('      * Number of RefMatch and AltMatch alleles RETAINED: ', retained_count)

    outp_log.write('# Only extract RefMatch and AltMatch alleles for determining allele identity and assigning existing IDs or new IDs\n')
    outp_log.write('    # Retain a RefMatch or AltMatch based on whichever is smaller below:\n')
    outp_log.write('      * At least 10 samples, each having a minimum of 2 reads\n') 
    outp_log.write('      * At least 5% samples, each having a minimum of 2 reads\n')
    outp_log.write('      * Number of RefMatch and AltMatch alleles DISCARDED: ' + str(miss_count) + '\n')
    outp_log.write('      * Number of RefMatch and AltMatch alleles RETAINED: ' + str(retained_count) + '\n')


if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Extract RefMatch and AltMatch microhaps into a FASTA file and assign temp names for them in the report")

    parser.add_argument('report',
                        help='MADC report')

    args=parser.parse_args()

    process_madc(args.report)
