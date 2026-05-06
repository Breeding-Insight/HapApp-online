#!/usr/bin/python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db02_update_snpID_in_madc_v1.py [-h] lut report
###############################################################################

def get_snpID_lut(lut):
    inp = open(lut, encoding='utf-8-sig')
    line = inp.readline()
    # Check if there is a header line
    if line.startswith('Panel_markerID'):
        line = inp.readline()
    else:
        pass
    snpID_lut = {}
    while line:
        # alfalfaRep2vsXJDY1_shared_918,chr1.1_000194324
        line_array = line.strip().split(',')
        snpID_lut[line_array[0]] = line_array[1]
        line = inp.readline()
    inp.close()
    print('Number of SNP IDs in the lookup table:', len(snpID_lut))
    return (snpID_lut)


def ext_ref_alt_amplicon_seq(report, snpID_lut):
    inp = open(report)
    line = inp.readline()
    outp_report = open(report.replace('.csv', '_snpID.csv'), 'w')
    outp_matchCnt_lut = open(report.replace('.csv', '_snpID_matchCnt_lut.txt'), 'w')
    removed_markers = []
    new_markerIDs_list = []
    while line:
        line_array = line.strip().split(',')
        if line_array[0] == '' or line_array[0] =='*' or line_array[0] == 'AlleleID':
            outp_report.write(line)
        else:
            '''
            VaccDscaff11_001337505|Ref
            VaccDscaff11_001337505|Alt
            VaccDscaff11_001337505|RefMatch
            VaccDscaff11_001337505|AltMatch
            '''
            old_snpID = line_array[0].split('|')[0]
            old_snpID_lc = old_snpID.lower()
            old_snpID_uc = old_snpID.capitalize()
            new_markerID = ''
            if old_snpID in snpID_lut:
                new_markerID = snpID_lut[old_snpID]
            elif old_snpID_lc in snpID_lut:
                #print("# Lower case:", old_snpID_lc, "is in the lookup table")
                new_markerID = snpID_lut[old_snpID_lc]
            elif old_snpID_uc in snpID_lut:
                #print("# Upper case:", old_snpID_lc, "is in the lookup table")
                new_markerID = snpID_lut[old_snpID_uc]
            else:
                pass

            if len(new_markerID) > 1:
                new_alleleID = line_array[0].replace(old_snpID, new_markerID)
                outp_report.write(new_alleleID + ',' + new_markerID + ',' + ','.join(line_array[2:]) + '\n')
                new_markerIDs_list.append(new_markerID)
                new_markerID = ''
            else:
                if old_snpID not in removed_markers:
                    removed_markers.append(old_snpID)
        line = inp.readline()
    print('[INFO] Number of markers with snpIDs updated: ', len(set(new_markerIDs_list)))
    print('[INFO] Markers not in lookup table and their associated MADC records are not written to the output:', len(removed_markers))
    print('    \n'.join(removed_markers))
    for i in set(new_markerIDs_list):
        outp_matchCnt_lut.write(i + '|RefMatch\t0\n')
        outp_matchCnt_lut.write(i + '|AltMatch\t0\n')
        outp_matchCnt_lut.write(i + '|Other\t0\n')
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
    
    print('  # Updating SNP IDs in MADC report')
    
    snpID_lut = get_snpID_lut(args.lut)
    
    ext_ref_alt_amplicon_seq(args.report, snpID_lut)
