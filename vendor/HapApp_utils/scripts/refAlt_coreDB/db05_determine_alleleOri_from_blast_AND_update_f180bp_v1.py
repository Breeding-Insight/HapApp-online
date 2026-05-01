#!/usr/bin/python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db05_determine_alleleOri_from_blast_AND_update_f180bp_v1.py [-h] blast fastaDB
###############################################################################

def rev_complement(seq):
    complement = {'A': 'T', 'C': 'G', 'G': 'C', 'T': 'A', '-':'-'}
    # IUPAC codes and their complements in a dict
    complement.update({'R': 'Y', 'Y': 'R', 'S': 'S', 'W': 'W', 'K': 'M', 'M': 'K', 'B': 'V', 'V': 'B', 'D': 'H', 'H': 'D', 'N': 'N'})
    seq_rev = "".join(complement.get(base, base) for base in reversed(seq.upper()))
    return(seq_rev)


def get_rev_compliment_fasta(fastaDB, alleles):
    inp = open(fastaDB)
    outp = open(fastaDB.replace('.fa', '_rev.fa'), 'w')
    outp_botloci = open(fastaDB.replace('.fa', '.botloci'), 'w')
    line = inp.readline()
    plus_count = 0
    minus = []
    missing_keys = []
    while line:
        if line.startswith('>'):
            allele_key = line[1:].strip()
            if allele_key not in alleles:
                missing_keys.append(allele_key)
                line = inp.readline()
                continue

            if alleles[allele_key][-1] == '-':
                # Add the markers on minus strand of the reference genome to a list
                marker = line.split('|')[0][1:]
                if marker not in minus:
                    minus.append(marker)

                outp.write(line)
                seq = inp.readline()
                seq = seq.strip()
                seq_rev = rev_complement(seq)
                outp.write(seq_rev + '\n')
            else:
                plus_count += 1
                outp.write(line)
                line = inp.readline()
                outp.write(line)
        else:
            print('Check')
        line = inp.readline()
    print('  # Number of marker loci on PLUS strand: ', int(plus_count/2))
    print('  # Number of marker loci on MINUS strand: ', len(minus))
    if missing_keys:
        print('  # Number of allele records with no orientation assignment: ', len(missing_keys))
        print('  # First missing allele IDs:', missing_keys[:5])
    for marker in minus:
        outp_botloci.write(marker + '\n')

    inp.close()
    outp.close()
    outp_botloci.close()


def ext_unique_hits_for_queries(blast):
    # VaccDscaff11_000042737|Ref_0001    54  1  54  VaccDscaff11_000042737|Ref  361     210     157     54  100     100.000 3.63e-25
    # chr05_004488015|Ref_0001	         81	 1	81	chr05_004488021|Ref	        301	    181	    101	    81	100	    100.000	4.93e-41
    inp = open(blast)
    line = inp.readline()
    alleles = {}
    # alleles: {'chr08_004336696|Ref', '601', '381', '273', '109', '100', '100.000', '2.13e-57', '-'], 'chr08_004336696|Alt': ['chr08_004336696|Alt_0002', '109', '1', '109', 'chr08_004336696|Alt', '601', '381', '273', '109', '100', '100.000', '2.13e-57', '-'], ...}
    while line:
        line_array = line.strip().split()
        if 'Ref' in line_array[0] or 'Alt' in line_array[0]:
            query_array = line_array[0].rsplit('_', 1)[0]
            subject_array = line_array[4]
            if query_array == subject_array:
                # Determine the alignment orientation and add a note to the line_array
                if int(line_array[6]) > int(line_array[7]):
                    line_array.append('-')
                else:
                    line_array.append('+')
    
                # Add information to a dictionary and make sure every subject sequence only appear once
                if line_array[4] not in alleles:
                    alleles[line_array[4]] = line_array
                else:
                    # Compare length of coverage
                    query_cov_inDict = abs(int(alleles[line_array[4]][3]) - int(alleles[line_array[4]][2])) + 1
                    query_cov = abs(int(line_array[3]) - int(line_array[2])) + 1
                    if query_cov > query_cov_inDict:
                        print('  # Update this query: \n', alleles[line_array[4]])
                        print('  # With this one:', line_array)
                        alleles[line_array[4]] = line_array
                    elif query_cov == query_cov_inDict:
                        # Compare alignment identity
                        if float(line_array[10]) > float(alleles[line_array[4]][10]):
                            print('  # Update this query: \n', alleles[line_array[4]])
                            print('  # With this one:', line_array)
                            alleles[line_array[0]] = line_array
                        else:
                            pass
                    else:
                        pass
            else:
                pass
        line = inp.readline()
    inp.close()
    print('  # Number of Ref and Alt alleles: ', len(alleles))
    if len(alleles) == 0:
        raise ValueError(
            'No matching BLAST hits were found where query and subject allele IDs agree. '
            'Check whether the BLAST query FASTA was generated from the SNP-ID-updated MADC report.'
        )
    return(alleles)


if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Extract fasta sequences of 3K DArTag panel")

    parser.add_argument('blast',
                        help='BLAST result of amplicon sequences to 180 bp flanking sequences')

    parser.add_argument('fastaDB',
                        help='Allele DB')

    args=parser.parse_args()
    
    print('  # Running db05_determine_alleleOri_from_blast_AND_update_f180bp_v1.py on', args.blast)

    alleles = ext_unique_hits_for_queries(args.blast)
    
    get_rev_compliment_fasta(args.fastaDB, alleles)
