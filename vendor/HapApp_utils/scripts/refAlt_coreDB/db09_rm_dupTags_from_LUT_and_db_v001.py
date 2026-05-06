#!/usr/bin/python3

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: db09_rm_dupTags_from_LUT_and_db_v001.py [-h] file dupTag
###############################################################################

def get_dup_tags(dupTag):
    inp = open(dupTag, 'r')
    line = inp.readline()
    dupTag_2_remove = []
    while line:
        line_array = line.strip().split('\t')
        # marker1   marker2
        # put marker2 in the list to be removed
        marker2 = line_array[1].split("|")[0]
        dupTag_2_remove.append(marker2)
        line = inp.readline()
    inp.close()
    print('[INFO] Number of marker loci needing removal:', len(dupTag_2_remove), dupTag_2_remove)
    return(dupTag_2_remove)



def remove_dup_tags(file, dupTag_2_remove):
    if file.endswith('snpID_lut.csv'):
        outp = open(file.replace('snpID_lut.csv', 'rmDupTag_snpID_lut.csv'), 'w')
        inp = open(file)
        line = inp.readline()
        outp.write(line)
        line = inp.readline() # The first data line
        while line:
            line_array = line.strip().split(',')
            if line_array[1] in dupTag_2_remove:
                print('[INFO] Remove from snpID lut table: {}'.format(line_array[1]))
            else:
                outp.write(line)
            line = inp.readline()
    elif file.endswith('sfetch.fa'):
        outp = open(file.replace('sfetch.fa', 'sfetch_rmDupTag.fa'), 'w')
        inp = open(file)
        line = inp.readline()
        seq = ''
        while line:
            if line.startswith('>'):
                if seq != '':
                    snpID = seqID.split("|")[0]
                    if snpID not in dupTag_2_remove:
                        outp.write('>' + seqID + '\n' + seq + '\n')
                    else:
                        print('[INFO] Remove from fasta file: ', seqID)
                seqID = line.replace('>', '').strip()
                seq = ''
            else:
                seq += line.strip()
            line = inp.readline()
        # Last sequence
        snpID = seqID.split("|")[0]
        if snpID not in dupTag_2_remove:
            outp.write('>' + seqID + '\n' + seq + '\n')
        else:
            print('[INFO] Remove from fasta file: ', seqID)
    elif file.endswith('matchCnt_lut.txt'):
        outp = open(file.replace('matchCnt_lut.txt', 'matchCnt_lut_rmDupTag.txt'), 'w')
        inp = open(file)
        line = inp.readline()
        while line:
            line_array = line.strip().split('\t')
            snpID = line_array[0].split("|")[0]
            if snpID in dupTag_2_remove:
                print('[INFO] Remove from matchCnt lut table: {}'.format(line_array[0]))
            else:
                outp.write(line)
            line = inp.readline()
    inp.close()
    outp.close()



if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Remove duplicate marker loci from snpID_lut.csv and the initial Ref and Alt sequences")

    parser.add_argument('file',
                        help='snpID_lut or Ref and Alt sequences')

    parser.add_argument('dupTag', help='A tsv file containing duplicate marker loci')

    args=parser.parse_args()

    dupTag_2_remove = get_dup_tags(args.dupTag)

    remove_dup_tags(args.file, dupTag_2_remove)