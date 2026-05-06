#!/usr/bin/python3

def collect_dupTag_closeTag(tags):
    inp = open(tags, encoding='utf-8-sig')
    dup_tags = [line.strip() for line in inp.readlines()]
    inp.close()
    print('# Number of markers need to be removed: ', len(dup_tags))
    return(dup_tags)


def rm_dupTag_closeTag(report, dup_tags, outf):
    inp = open(report)
    outp = open(outf, 'w')
    line = inp.readline()
    cnt = 0
    while line:
        if not line.startswith('*') and not line.startswith(' '):
            line_array = line.strip().split(',')
            # ['Chr12_24488267|RefMatch', 'Chr12_24488267', 'CTTCCACCTCTCCTCCAATGCTTATGTCCAAAAAGCACTTCG...',...]
            if line_array[1] not in dup_tags:
                outp.write(line)
            else:
                cnt += 1
        else:
            outp.write(line)
        line = inp.readline()
    print('# Number of microhaplotypes removed:', cnt)
    inp.close()
    outp.close()



if __name__=='__main__':

    import argparse

    parser=argparse.ArgumentParser(description="Generate stats from missing allele count")

    parser.add_argument('tags',
                        help='A file containing the passport data of the samples in the report')

    parser.add_argument('report',
                        help='Reformated DArTag report, including fixed alleleIDs')

    parser.add_argument('outf', help='Output file name')

    args=parser.parse_args()

    dup_tags = collect_dupTag_closeTag(args.tags)

    rm_dupTag_closeTag(args.report, dup_tags, args.outf)
