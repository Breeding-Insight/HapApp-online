#!/bin/bash
# Base db was already generated for REF and ALT alleles

# Note: change here ###### The readme file should be one version above the current db version
# If no new alleles are found, give the readme file another name
PROCESS_README='/Users/dz359/PycharmProjects/BI/sweetpotato_dartag_00_microhaplotype_db/data/sweetpotato_allele_db_v015_process.readme'
NO_NEW_ALLELE_README='/Users/dz359/PycharmProjects/BI/sweetpotato_dartag_00_microhaplotype_db/data/sweetpotato_allele_db_v014_DSp24-9714_noNewAllele.readme'
exec &> $PROCESS_README

# Scripts and files
SCRIPTS_DIR='/Users/dz359/PycharmProjects/BI/01_dartag_alleles/code/02_fixedAlleleID'
CODE_VER='v1'
MARKERID_LUT='/Users/dz359/PycharmProjects/BI/sweetpotato_dartag_00_microhaplotype_db/data/sweetpotato_20K_SNPset_f180bp_forDArT_3K_snpID_lut.csv'
ALLELE_DB_DIR='/Users/dz359/PycharmProjects/BI/sweetpotato_dartag_00_microhaplotype_db/data'
ALLELE_DB='sweetpotato_allele_db_v014.fa'
MATCHCNT_LUT='sweetpotato_allele_db_v014_matchCnt_lut.txt'
REPORT='/Users/dz359/PycharmProjects/BI/sweetpotato_dartag_P04_leafRoot_2plates/data/Report-DSp24-9714/DSp24-9714_MADC.csv'
FIRST_SAMPLE_COL=17

# Marker panel information
DESIGN_LEN=81
SEQ_LEN=109


# Processing starts here
now=$(date)
printf "%s\n" "$now"

printf "\n# 1). Update snpIDs to Chr_00xxxxxxx format in MADC"
printf "\n  # This is necessary because marker IDs do not always follow the Chr_00xxxxxxx format\n"
REPORT_SNPID=${REPORT%????}'_snpID.csv'
if [ -f $REPORT_SNPID ]; then
    echo "$REPORT_SNPID exists. Skip this step."
else
    python $SCRIPTS_DIR/step00_madc_update_snpID_v1.py $MARKERID_LUT $REPORT
fi


printf "\n# 2). Check if there are any duplicate alleles - same microhaplotypes with different IDs"
printf "\n  # If there are duplicates, retain only one allele of the duplicated ones\n"
python $SCRIPTS_DIR/step00_check_allele_uniqueness_AND_update_madc_v1.py $REPORT_SNPID $FIRST_SAMPLE_COL
REPORT_SNPID_UNIQ=${REPORT%????}'_snpID_uniq.csv'
if test -f "$REPORT_SNPID_UNIQ"; then
    printf "\n  # Updated MADC file: $REPORT_SNPID_UNIQ\n"
    REPORT_SNPID=$REPORT_SNPID_UNIQ
else
    printf "\n  # No duplicates found in MADC file\n"
fi


printf "\n# 3). Filter alleles with missing data and generate RefMatch and AltMatch allele fasta and a temporary report\n"
python $SCRIPTS_DIR/step01_filter_missing_AND_ext_matchAlleles_from_madc_v1.py $REPORT_SNPID
# The output of this step is a temporary report file with renamed marker IDs and RefMatch and AltMatch allele fasta files
TMP_RENAME=${REPORT_SNPID%????}'_tmp_rename.csv'
MATCH_ALLELES=${REPORT_SNPID%????}'_match.fa'


printf "\n#  4). Remove adapters using cutadapt"
#  -n COUNT, --times COUNT
#                        Remove up to COUNT adapters from each read. Default: 1
#  -O MINLENGTH, --overlap MINLENGTH
#                        Require MINLENGTH overlap between read and adapter for an adapter to be found.
#                        Default: 3
# -a ACCGATCTCGTATGCCGTCTTCTGCTTG 
if [ $DESIGN_LEN -eq $SEQ_LEN ]; then
    printf "\n  # Both design length and sequencing length are the same. No need to run adaptor checking\n"
else
    printf "\n  # Sequencing length is longer than panel design length, run cutadapt\n"
    CUTADAPT=${REPORT_SNPID%????}'_match_cutadapt.fa'
    CUT_LOG=${REPORT_SNPID%????}'_match_cutadapt.log'
    /Users/dz359/Library/Python/3.9/bin/cutadapt -a ACCGATCTG -e 0.3 -n 1 --overlap 5 -m $DESIGN_LEN -o $CUTADAPT $MATCH_ALLELES > $CUT_LOG
    # Some Illumina instruments use a two-color chemistry to encode the four bases. This includes the NextSeq and the NovaSeq. 
    # In those instruments, a ‘dark cycle’ (with no detected color) encodes a G. 
    # However, dark cycles also occur when sequencing “falls off” the end of the fragment. 
    # The read then contains a run of high-quality, but incorrect “G” calls at its 3’ end.
    MATCH=$(grep -c ">" $MATCH_ALLELES)
    MATCH_CUT=$(grep -c ">" $CUTADAPT)
    printf "\n    # Number of RefMatch and AltMatch extracted from MADC: $MATCH"
    printf "\n    # Number of RefMatch and AltMatch retained after cutadapt: $MATCH_CUT\n" 
    
    printf "\n#  5). Check if there are duplicate alleles after removing adapters AND update allele sequences and read counts\n"
    printf "  # CUTADAPT file: $CUTADAPT\n"
    printf "  # Temporary rename file: $TMP_RENAME\n"
    python $SCRIPTS_DIR/step03_check_cutadapt_allele_uniqueness_AND_update_tmp_rename_report_v1.1.py $CUTADAPT $ALLELE_DB_DIR/$ALLELE_DB $TMP_RENAME
    CUTADAPT_UNI=${REPORT_SNPID%????}'_match_cutadapt_unique.fa'
    TMP_RENAME_UPDATED=${REPORT_SNPID%????}'_tmp_rename_updatedSeq.csv'
fi


##This might be necessary fue to some errors about the blast database memory map (added by Alex)
printf "\n#  6a). First, create the BLAST database"
# 1. First, create the BLAST database
makeblastdb -in $ALLELE_DB_DIR/$ALLELE_DB \
            -dbtype nucl \
            -parse_seqids
            
printf "\n#  6b). BLAST RefMatch and AltMatch against the allele db\n"
# If there are no duplicate alleles, there won't be the a '_match_cutadapt_unique.fa'
# There won't be a '_tmp_rename_updatedSeq.csv' either
# Here, use if else to execute different input files.
if test -f "$CUTADAPT"; then
    if test -f "$CUTADAPT_UNI"; then
      BLAST_DBBLAST=${REPORT_SNPID%????}'_match_cutadapt_unique.fa.alleledb.bn'
      blastn -task blastn-short -dust no -soft_masking false -db $ALLELE_DB_DIR/$ALLELE_DB -query $CUTADAPT_UNI -out $BLAST_DBBLAST -evalue 1e-5 -num_threads 6 -max_target_seqs 5 -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'
    else
      BLAST_DBBLAST=${REPORT_SNPID%????}'_match_cutadapt.fa.alleledb.bn'
      blastn -task blastn-short -dust no -soft_masking false -db $ALLELE_DB_DIR/$ALLELE_DB -query $CUTADAPT -out $BLAST_DBBLAST -evalue 1e-5 -num_threads 6 -max_target_seqs 5 -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'
    fi 
else
    BLAST_DBBLAST=${REPORT_SNPID%????}'_match.fa.alleledb.bn'
    blastn -task blastn-short -dust no -soft_masking false -db $ALLELE_DB_DIR/$ALLELE_DB -query $MATCH_ALLELES -out $BLAST_DBBLAST -evalue 1e-5 -num_threads 6 -max_target_seqs 5 -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'
fi


printf "\n#  7). Determine status of RefMatch and AltMatch and Assign fixed IDs to them\n"

if test -f "$CUTADAPT_UNI"; then
    python $SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py $ALLELE_DB_DIR/$MATCHCNT_LUT $ALLELE_DB_DIR/$ALLELE_DB $TMP_RENAME_UPDATED $BLAST_DBBLAST
    MADC_CLEANED=${REPORT_SNPID%????}'_rename_updatedSeq.csv'
else
    python $SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py $ALLELE_DB_DIR/$MATCHCNT_LUT $ALLELE_DB_DIR/$ALLELE_DB $TMP_RENAME $BLAST_DBBLAST
    MADC_CLEANED=${REPORT_SNPID%????}'_rename.csv'
fi



printf "\n#  8). Check if there is a new version DB\n"
# If there are new alleles added to the db, a new version of db will be generated
# Otherwise, no new db
VER=$(echo $ALLELE_DB | grep -o 'v[0-9]\{3\}' | cut -c2- | sed 's/^0*//')
NEW_VER=$(printf '%03d' $(($VER+1)))
ALLELE_DB_NEW=${ALLELE_DB%??????}$NEW_VER'.fa'
if test -f "$ALLELE_DB_DIR/$ALLELE_DB_NEW"; then
    printf "  # New version of db created after adding noval alleles.\n"
    printf "  $ALLELE_DB_DIR/$ALLELE_DB_NEW\n"
    makeblastdb -in $ALLELE_DB_DIR/$ALLELE_DB_NEW -dbtype nucl
    
    printf "\n#  9). Check if there are duplicates."
    printf "  # If there are duplicates, retain only one allele of the duplicated ones\n"
    #cat $ALLELE_DB_NEW_BLAST | awk '$1!=$5 && $10==100 && $11==100.0' | more
    python $SCRIPTS_DIR/step06_check_db_allele_uniqueness_v1.py $ALLELE_DB_DIR/$ALLELE_DB_NEW
    
    printf "\n#  10). If there are duplicates in the new version DB, update MADC after removing duplicated alleles in db\n"
    DUP=$ALLELE_DB_DIR/$ALLELE_DB_NEW'.dup.csv'
    if test -f "$DUP"; then
        VER=$(echo $ALLELE_DB | grep -o 'v[0-9]\{3\}' | cut -c2- | sed 's/^0*//')
        NEW_VER_RMDUP=$(printf '%03d' $(($VER+2)))
        ALLELE_DB_NEW_RMDUP=${ALLELE_DB%??????}$NEW_VER_RMDUP'.fa'
        makeblastdb -in $ALLELE_DB_DIR/$ALLELE_DB_NEW_RMDUP -dbtype nucl
        printf "  # There are duplicate alleles in db. Check if these duplicate alleles are in MADC file.\n"
        python $SCRIPTS_DIR/step06_update_MADC_with_allele_uniqueness_v1.py $DUP $MADC_CLEANED
        printf "\n#  11). Add version of the script to the MADC with fixed allele IDs\n"
        if test -f "$CUTADAPT_UNI"; then
            MADC_CLEANED_RMDUP=${REPORT_SNPID%????}'_rename_updatedSeq_rmDup.csv'
            MADC_CLEANED_RMDUP_VER=${REPORT_SNPID%????}'_rename_updatedSeq_rmDup_'$CODE_VER'.csv'
        else
            MADC_CLEANED_RMDUP=${REPORT_SNPID%????}'_rename_rmDup.csv'
            MADC_CLEANED_RMDUP_VER=${REPORT_SNPID%????}'_rename_rmDup_'$CODE_VER'.csv'
        fi
        awk -v val="$CODE_VER" 'NR==1{print "Code_version," $0} NR>1{print val "," $0}' $MADC_CLEANED_RMDUP > $MADC_CLEANED_RMDUP_VER
    else
        printf "  # No duplicate alleles found in microhap db\n"
        echo $ALLELE_DB_DIR/$ALLELE_DB_NEW
        printf "\n#  11). Add version of the script to the MADC with fixed allele IDs\n"
        if test -f "$CUTADAPT_UNI"; then
            MADC_CLEANED_VER=${REPORT_SNPID%????}'_rename_updatedSeq_'$CODE_VER'.csv'
        else
            MADC_CLEANED_VER=${REPORT_SNPID%????}'_rename_'$CODE_VER'.csv'
        fi
        awk -v val="$CODE_VER" 'NR==1{print "Code_version," $0} NR>1{print val "," $0}' $MADC_CLEANED > $MADC_CLEANED_VER
        printf "  # Version added to as the first column of the output file.\n"
    fi 
else
    printf "  # No new alleles found, therefore, no new db generated.\n"
    mv $PROCESS_README $NO_NEW_ALLELE_README
fi

printf "\n###### Complete! #######\n"
