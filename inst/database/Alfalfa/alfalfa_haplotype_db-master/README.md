# alfalfa_haplotype_db
All haplotypes from DArTag genotyping of alfalfa


Note: the initial probe design for the alfalfa DArTag panel was optimal for 54 bp amplicons, which was later changed to 81 bp by DArT in Fall 2022. Therefore, the haplotype database is a mixture of haplotypes ranging from 54-81 bp.

# 2024.3.21
When populating microhaplotype db with new MADC files, the original "remove duplicates" process is flawed because removed haplotypes may be present in previous processed MADC files. Improvements were made in this version of microhaplotype db pipeline.
For duplicated alleles, retain the one with the longest sequence. If duplicated alleles are the same length, retain the one with small ID number. This means the most recently added alleles will be removed, which won't have less impact on previous MADC files. If there are still microhaplotypes in MADC files not present in the most recent microhaplotype db, then do a BLAST search and assign that non-existent allele a new ID.
