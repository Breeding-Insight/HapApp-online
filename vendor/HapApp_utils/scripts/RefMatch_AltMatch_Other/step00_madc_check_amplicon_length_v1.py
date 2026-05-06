#!/usr/bin/python3

def determine_amplicon_length(report):
    import re
    inp = open(report)
    line = inp.readline()
    outp_report = open(report.replace('.csv', '_ampLength.csv'), 'w')
    amp_len_list = []
    while line:
        line_array = line.strip().split(',')
        if line_array[0] == '' or line_array[0] =='*':
            pass
        elif 'AlleleID' in line_array[0]:
            samples = line_array[16:]
        else:
            amp_len = len(line_array[2])
            if str(amp_len) not in amp_len_list:
                amp_len_list.append(str(amp_len))
            else:
                pass
        line = inp.readline()
    inp.close()
    print('# Amplicon length:', amp_len_list)
    print('# Number of Samples:', len(samples))
    outp_report.write('Amplicon Length:,' + ','.join(amp_len_list) + '\n')
    outp_report.write('Number of Samples:,' + str(len(samples)) + '\n')
    outp_report.write('\nSample Names:\n' + '\n'.join(samples) + '\n')
    outp_report.close()



if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Generate stats from missing allele count")
    
    parser.add_argument('report',
                        help='Missing allele report with allele name reformatted and unique sample names')

    args=parser.parse_args()
    
    determine_amplicon_length(args.report)
