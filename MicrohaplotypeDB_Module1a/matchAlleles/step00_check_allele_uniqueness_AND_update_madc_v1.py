#!/usr/bin/python3

def write_to_output(outf, header, allele_dict):
    outp = open(outf, 'w')
    outp.write(header)
    for value in allele_dict.values():
        outp.write(','.join(value) + '\n')
    outp.close()
    
def determine_allele_status(madc, first_sample_column):
    inp = open(madc)
    line = inp.readline()
    header = ''
    alleles = {}
    dup_alleles = {}
    while line:
        if line.startswith('AlleleID'):
            header = line
            line = inp.readline()
        else:
            pass
        
        if header != '':
            line_array = line.strip().split(',')
            if line_array[2] not in alleles:
                alleles[line_array[2]] = line_array
            else:
                concat = []
                for i, j in zip(alleles[line_array[2]][int(first_sample_column) - 1:], line_array[int(first_sample_column) - 1:]):
                    concat.append(str(int(i) + int(j)))
                print('hap 1:', alleles[line_array[2]])
                print('hap 2:', line_array)
                print('concatenated:', concat)
                if line_array[2] not in dup_alleles:
                    dup_alleles[line_array[2]] = ['hap 1'] + alleles[line_array[2]] + ['\n']
                    dup_alleles[line_array[2]] += (['hap 2'] + line_array + ['\n'])
                else:
                    dup_alleles[line_array[2]] += (['hap 2'] + line_array + ['\n'])
                dup_alleles[line_array[2]] += (['concatenated'] + line_array[:3] + concat + ['\n'])
                alleles[line_array[2]] = alleles[line_array[2]][:int(first_sample_column)] + concat
        else:
            pass
        line = inp.readline()
    inp.close()

    if dup_alleles != {}:
        print('There are duplicated alleles in this MADC report')
        outf = madc.replace('.csv', '_uniq.csv')
        write_to_output(outf, header, alleles)

        outf_dup = madc.replace('.csv', '_dup.csv')
        write_to_output(outf_dup, header, dup_alleles)
    else:
        print('There are no duplicated alleles in this MADC report')



if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Check whether there are duplicate allele sequences with the different allele names")

    parser.add_argument('madc', help='Raw or processed MADC with alleles assigned fixed IDs')

    parser.add_argument('first_sample_column', help='The column containing the first sample data')
    
    args = parser.parse_args()

    determine_allele_status(args.madc, args.first_sample_column)
