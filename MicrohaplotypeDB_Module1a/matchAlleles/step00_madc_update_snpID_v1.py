#!/usr/bin/python3

def get_snpID_lut(lut):
    inp = open(lut, encoding='utf-8-sig')
    line = inp.readline()
    snpID_lut = {}
    while line:
        # alfalfaRep2vsXJDY1_shared_918,chr1.1_000194324
        line_array = line.strip().split(',')
        snpID_lut[line_array[0]] = line_array[1]
        line = inp.readline()
    inp.close()
    return(snpID_lut)


def update_snpID(report, snpID_lut):
    import re
    inp = open(report)
    line = inp.readline()
    outp_report = open(report.replace('.csv', '_snpID.csv'), 'w')
    while line:
        line_array = line.strip().split(',')
        if line_array[0] == '' or line_array[0] =='*' or 'AlleleID' in line_array[0]:
            outp_report.write(line)
        else:
            '''
            VaccDscaff11_001337505|Ref
            VaccDscaff11_001337505|Alt
            LG1_alfalfaRep2vsXJDY1_shared_3958_SNP1
            '''
            if '|' in line_array[0]:
                old_snpID = line_array[0].split('|')[0]
                if old_snpID in snpID_lut:
                    new_markerID = snpID_lut[old_snpID]
                    new_alleleID = line_array[0].replace(old_snpID, new_markerID)
                    outp_report.write(new_alleleID + ',' + new_markerID + ',' + ','.join(line_array[2:]) + '\n')
                else:
                    print(old_snpID, 'not found in lookup table')
            elif line_array[0].startswith('LG'):
                old_markerID = '_'.join(line_array[0].split('_')[1:-1])
                new_markerID = snpID_lut[old_markerID]
                outp_report.write(line_array[0] + ',' + new_markerID + ',' + ','.join(line_array[1:]) + '\n')
            else:
                print(line)
        line = inp.readline()
    inp.close()
    outp_report.close()



if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Generate stats from missing allele count")

    parser.add_argument('lut',
                        help='SNP ID lookup table')
    
    parser.add_argument('report',
                        help='Missing allele report with allele name reformatted and unique sample names')

    args=parser.parse_args()
    
    snpID_lut = get_snpID_lut(args.lut)
    
    update_snpID(args.report, snpID_lut)
