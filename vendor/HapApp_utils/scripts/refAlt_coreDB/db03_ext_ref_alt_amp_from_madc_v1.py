#!/usr/bin/python3


###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db03_ext_ref_alt_amp_from_madc_v1.py [-h] report
###############################################################################

def ext_ref_alt_amplicon_seq(report):
    inp = open(report)
    line = inp.readline()
    outp_fasta = open(report.replace('.csv', '_ref_alt_amplicons.fa'), "w")
    outp_iupac = open(report.replace('.csv', '_iupac.csv'), "w")
    cnt = 0
    iupac = {'R': 'AG', 'Y': 'CT', 'S': 'GC', 'W': 'AT', 'K': 'GT', 'M': 'AC', 'B': 'CGT', 'D': 'AGT', 'H': 'ACT', 'V': 'ACG', 'N': 'ACGT'}
    while line:
        line_array = line.strip().split(',')
        if line_array[0] == '' or line_array[0] =='*' or line_array[0] == 'AlleleID':
            pass
        else:
            '''
            VaccDscaff11_001337505|Ref
            VaccDscaff11_001337505|Alt
            '''
            iupac_code = False

            if line_array[0].endswith('Ref'):
                allele_ID = line_array[0] + '_0001'
                outp_fasta.write('>' + allele_ID + '\n' + line_array[2] + '\n')
                for key in iupac:
                    if key in line_array[2]:
                        iupac_code = True
                    else:
                        pass

                if iupac_code:
                    outp_iupac.write(line_array[0] + '\t' + line_array[2] + '\n')
                    cnt += 1
            elif line_array[0].endswith('Alt'):
                allele_ID = line_array[0] + '_0002'
                outp_fasta.write('>' + allele_ID + '\n' + line_array[2] + '\n')
            else:
                pass
        line = inp.readline()
    inp.close()

    outp_fasta.close()
    outp_iupac.close()
    print('[INFO] Number of marker loci containing IUPAC codes: ', cnt)



if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Extract Ref and Alt alleles from MADC report and check if there are duplicate alleles")

    parser.add_argument('report',
                        help='Raw MADC report')

    args=parser.parse_args()

    ext_ref_alt_amplicon_seq(args.report)
