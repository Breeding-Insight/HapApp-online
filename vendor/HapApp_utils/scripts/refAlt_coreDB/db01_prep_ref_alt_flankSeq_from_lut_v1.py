#!/usr/bin/python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db01_prep_ref_alt_flankSeq_from_lut_v1.py [-h] [--snpID_lut SNPID_LUT] [--flankSeq FLANKSEQ] [--flank_len FLANK_LEN]
###############################################################################

def get_ref_alt_bases(markerIDs):
    '''
    Added this function to consider the case of Indels
    Get reference and alternate bases for each markerID
    For indel annotation:
    # OFP20_M6_CDS_75	M6_chr10_48867893_000000225	M6_chr10_48867893	225	    T	   TAGC	Indel *coordinate of the anchor base (the one before the insertion
    # OFP20_M6_CDS_290	M6_chr10_48867893_000000441	M6_chr10_48867893	441	TCACGATGT	T	Indel *coordinate of the anchor base (the one before the deletion)
    # OFP20_M6_CDS_75	M6_chr10_48867893_000000225	M6_chr10_48867893	225	    T	   -	Indel *coordinate of the deleted base for single-base deletions in variants
    [       0                               1             2               3    4        5      6]
    '''
    inp = open(markerIDs, 'r')
    line = inp.readline()
    ref_alt_bases={}
    while line:
        line_array = line.strip().split(',')
        ref_alt_bases[line_array[1]] = [line_array[4].upper(), line_array[5].upper()]
        line = inp.readline()
    inp.close()
    return ref_alt_bases

def get_flankSeq(flankSeq):
    inp = open(flankSeq, 'r')
    line = inp.readline()
    flank = {}
    seq = ''
    markerID = None
    while line:
        if line.startswith('>'):
            if seq != '':
                flank[markerID] = seq.upper()
            else:
                pass
            markerID = line.strip().split()[0][1:]
            seq = ''
        else:
            seq += line.strip()
        line = inp.readline()
    if markerID is None:
        raise ValueError(f'Input flank sequence file is not valid FASTA or contains no records: {flankSeq}')
    # Last sequence
    flank[markerID] = seq.upper()
    inp.close()
    return(flank)


def pre_ref_alt_flankSeq(flank, ref_alt_bases, flank_len, outf_base):
    outp = open(outf_base.replace('.fa', '_ref_alt.fa'), 'w')
    flipped_ref_alt = []
    flipped_cnt = 0
    # flank contains the reference sequences
    for key, value in flank.items():
        if key in ref_alt_bases:
            # ['CT', 'TA']
            ref = ref_alt_bases[key][0]
            alt = ref_alt_bases[key][1]
            if len(ref) == len(alt) and alt != '-':
                ref_in_flank = value[int(flank_len):int(flank_len) + len(ref)].upper()
                # SNP: include 2 consecutive SNPs
                # OFP20_M6_CDS_75	M6_chr10_48867893_000000225	M6_chr10_48867893	225	T	A	SNP
                # OFP20_M6_CDS_290	M6_chr10_48867893_000000441	M6_chr10_48867893	441	TA	CG	SNP
                if ref_in_flank == ref:
                    #print('match', ref_in_flank, ref)
                    outp.write('>' + key + '|Ref\n' + value + '\n')
                    outp.write('>' + key + '|Alt\n' + value[:int(flank_len)] + alt + value[int(flank_len) + len(ref):] + '\n')
                elif ref_in_flank == alt:
                    # There is a special case in the grape panel where the ref and alt bases are swapped from Stacks vcf
                    # Will use the reference base as reference, swap Ref and Alt in the output
                    outp.write('>' + key + '|Ref\n' + value + '\n')
                    outp.write('>' + key + '|Alt\n' + value[:int(flank_len)] + ref + value[int(flank_len) + len(ref):] + '\n')
                    flipped_ref_alt.append([key, ref_alt_bases[key][0], ref_alt_bases[key][1], ref_in_flank])
                    flipped_cnt += 1
                else:
                    print('[INFO] non-matching marker:', key, ref_in_flank, ref_alt_bases[key])
            else:
                # Indels
                if alt == '-':
                    # single-base deletion in variant
                    # OFP20_M6_CDS_290	M6_chr10_48867893_000000441	M6_chr10_48867893	441	T	-	Indel
                    del_in_alt = len(ref)
                    outp.write('>' + key + '|Ref\n' + value + '\n')
                    outp.write('>' + key + '|Alt\n' + value[:int(flank_len)] + value[int(flank_len) + del_in_alt:] + '\n')
                elif len(ref) > len(alt):
                    # multi-base deletion in variant
                    # OFP20_M6_CDS_290	M6_chr10_48867893_000000441	M6_chr10_48867893	441	TCACGATGT	T	Indel
                    del_in_alt = len(ref) - len(alt)
                    outp.write('>' + key + '|Ref\n' + value + '\n')
                    outp.write('>' + key + '|Alt\n' + value[:int(flank_len) + 1] + value[int(flank_len) + 1 + del_in_alt:] + '\n')
                elif len(ref) < len(alt):
                    # insertions in variant
                    # OFP20_M6_CDS_75	M6_chr10_48867893_000000225	M6_chr10_48867893	225	T	TAGC	Indel
                    outp.write('>' + key + '|Ref\n' + value + '\n')
                    outp.write('>' + key + '|Alt\n' + value[:int(flank_len)] + alt + value[int(flank_len) + 1:] + '\n')
    outp.close()
    print('[INFO] Number of markers with Ref and Alt swapped: ', flipped_cnt)
    if len(flipped_ref_alt) > 0:
        outp_flipped = open(outf_base.replace('.fa', '_flippedRefAlt.csv'), 'w')
        outp_flipped.write('MarkerID,Ref,Alt,FlankSeqBase\n')
        for marker in flipped_ref_alt:
            outp_flipped.write(','.join(marker) + '\n')
        outp_flipped.close()
    else:
        print('[INFO] No Ref and Alt swapped markers found\n')


if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Extract flanking sequences (Ref and Alt) of 3K DArTag panel and generate snpID lookup table")

    parser.add_argument('--snpID_lut',
                        help='Marker ID look up table with ref and alt bases')
    
    parser.add_argument('--flankSeq',
                        help='Flanking sequences of the markers in fasta format')
    
    parser.add_argument('--flank_len',
                        help='Length of the left-side flanking sequence')

    args=parser.parse_args()

    ref_alt_bases = get_ref_alt_bases(args.snpID_lut)

    flank = get_flankSeq(args.flankSeq)

    pre_ref_alt_flankSeq(flank, ref_alt_bases, args.flank_len, args.flankSeq)
