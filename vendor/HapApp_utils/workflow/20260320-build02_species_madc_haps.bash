#!/bin/bash
#set -e This flag causes the pipeline to stop if any command line errors are detected

###############################################################################
###	 @author: Dongyan Zhao
###  @email: dongyan.zhao@ufl.edu
###  @date: 03/30/2026
###  Usage: bash 20260320-build02_species_madc_haps.bash
###############################################################################

# Base db was already generated for REF and ALT alleles

# Note: change here ###### The readme file should be one version above the current db version
# If no new alleles are found, give the readme file another name
PROCESS_README='../data/DCnutv2_allele_db_v003_process.readme'
NO_NEW_ALLELE_README='../data/DCnutv2_allele_db_v003_report_noNewAllele.readme'
exec &> "$PROCESS_README"

# Scripts and files
SCRIPTS_DIR='../scripts/RefMatch_AltMatch_Other'
CODE_VER='v1'
SNPID_LUT='../data/flankseq/chestnut_DArTag-probe-design-v2_type_snpID_lut.csv'
ALLELE_DB_DIR='../data'
ALLELE_DB_BASE='DCnutv2_allele_db_v002.fa'
MATCHCNT_LUT_BASE='DCnutv2_allele_db_v002_matchCnt_lut.txt'
ALLELE_DB_INDEL='DCnutv2_allele_db_v002_indelsAdded.fa'
MATCHCNT_LUT_INDEL='DCnutv2_allele_db_v002_indelsAdded_matchCnt_lut.txt'
REPORT='../data/genotyping_report/DCnut25-10895_MADC.csv'
FIRST_SAMPLE_COL=17
#DUP_TAGS='../data/genotyping_report/DCnut24-9430_MADC_dupTags_to_remove.txt'

# Marker panel information
DESIGN_LEN=81
SEQ_LEN=109


# BLAST thresholds
COV=90
IDEN=85 #Lowered threshold to recover some of the stringently filtered mHaps



# Processing starts here
now=$(date)
printf "%s\n" "$now"
printf "\n --- Scripts, files, and parameters used ---\n"
printf "# Report: $REPORT\n"
printf "# First sample column: $FIRST_SAMPLE_COL\n"
printf "# Panel design length: $DESIGN_LEN\n"
printf "# Sequencing length: $SEQ_LEN\n"
printf '# BLAST filtering thresholds: %s%% coverage, %s%% identity\n' "$COV" "$IDEN"

if [ -f "$ALLELE_DB_DIR/$ALLELE_DB_INDEL" ] && [ -f "$ALLELE_DB_DIR/$MATCHCNT_LUT_INDEL" ]; then
    ALLELE_DB="$ALLELE_DB_INDEL"
    MATCHCNT_LUT="$MATCHCNT_LUT_INDEL"
    printf "# Base DB input: %s\n" "$ALLELE_DB"
elif [ -f "$ALLELE_DB_DIR/$ALLELE_DB_BASE" ] && [ -f "$ALLELE_DB_DIR/$MATCHCNT_LUT_BASE" ]; then
    ALLELE_DB="$ALLELE_DB_BASE"
    MATCHCNT_LUT="$MATCHCNT_LUT_BASE"
    printf "# Base DB input: %s\n" "$ALLELE_DB"
else
    printf '[ERROR] Could not locate either base DB variant in %s\n' "$ALLELE_DB_DIR" >&2
    exit 1
fi


printf "\n# 1). Update snpIDs to Chr_00xxxxxxx format in MADC"
printf "\n  # This is necessary because marker IDs do not always follow the Chr_00xxxxxxx format\n"
REPORT_SNPID=${REPORT%????}'_snpID.csv'
python3 "$SCRIPTS_DIR/step00_madc_update_snpID_v1.1.py" "$SNPID_LUT" "$REPORT"



# Remove duplicate tags and keep only unique tags
printf "\n###### Start processing MADC file ######\n"
printf "\n# 0). Remove duplicate tags."
DUP_TAGS_DEFAULT=${REPORT%????}'_dupTags_to_remove.txt'
shopt -s nullglob
dup_cluster_candidates=( "${REPORT%????}"_snpID_ref_alt_amplicons.fa.f*bp_rev_${SEQ_LEN}bp_sfetch_ref_only_dupTag_cluster_nonSelf.tsv )
shopt -u nullglob

if [[ -z "${DUP_TAGS}" && -f "${DUP_TAGS_DEFAULT}" ]]; then
    DUP_TAGS="${DUP_TAGS_DEFAULT}"
    printf "\n  # Use existing duplicate tags file: %s\n" "$DUP_TAGS"
elif [[ -z "${DUP_TAGS}" && ${#dup_cluster_candidates[@]} -eq 1 ]]; then
    DUP_TAG_CLUSTER="${dup_cluster_candidates[0]}"
    printf "\n  # Derive duplicate tags from build01 cluster file: %s\n" "$DUP_TAG_CLUSTER"
    awk -F '\t' 'NF >= 2 { split($2, a, "|"); print a[1] }' "$DUP_TAG_CLUSTER" | sort -u > "$DUP_TAGS_DEFAULT"
    if [[ -s "${DUP_TAGS_DEFAULT}" ]]; then
        DUP_TAGS="${DUP_TAGS_DEFAULT}"
        printf "\n  # Derived duplicate tags file: %s\n" "$DUP_TAGS"
    else
        printf "\n  # Duplicate-tag cluster file is empty. Skipping duplicate tag removal step.\n"
    fi
elif [[ -z "${DUP_TAGS}" && ${#dup_cluster_candidates[@]} -gt 1 ]]; then
    printf "\n  # Multiple build01 duplicate-tag cluster files found. Set DUP_TAGS explicitly.\n"
    for dup_cluster in "${dup_cluster_candidates[@]}"; do
        printf "\n    - %s" "$dup_cluster"
    done
    exit 1
fi

if [[ -z "${DUP_TAGS}" ]]; then
    printf "\n  # No duplicate tags file provided or derived. Skipping duplicate tag removal step.\n"
elif [[ ! -f "${DUP_TAGS}" ]]; then
    printf "\n  # Duplicate tags file not found: %s\n" "$DUP_TAGS"
    exit 1
else
    printf "\n  # Duplicate tags file: $DUP_TAGS\n"
    REPORT_SNPID_RMDUP=${REPORT_SNPID%????}'_rmDup.csv'
    python3 "$SCRIPTS_DIR/step00_rm_dupTag_closeTag_rawMADC_v1.py" "$DUP_TAGS" "$REPORT_SNPID" "$REPORT_SNPID_RMDUP"
    printf "\n  # SNPID-updated MADC file with duplicate tags removed: $REPORT_SNPID_RMDUP\n"
    REPORT_SNPID=$REPORT_SNPID_RMDUP
fi


printf "\n# 2). Check if there are any duplicate alleles - same microhaplotypes with different IDs"
printf "\n  # If there are duplicates, output the duplicates and stop running the pipeline\n"
# https://stackoverflow.com/questions/947897/how-to-comment-a-block-of-code-in-bash

python3 "$SCRIPTS_DIR/step00_check_allele_uniqueness.py" "$REPORT_SNPID" "$FIRST_SAMPLE_COL"
REPORT_SNPID_DUP=${REPORT_SNPID%????}'_dup.csv'
if test -f "$REPORT_SNPID_DUP"; then
    printf "\n  # Check duplicated microhaplotypes\n"
    exit 0
else
    printf "\n  # No duplicates found in MADC file\n"
fi


printf "\n# 3). Filter alleles with missing data and generate RefMatch and AltMatch allele fasta and a temporary report\n"
python3 "$SCRIPTS_DIR/step01_filter_missing_AND_ext_matchAlleles_from_madc_v1.py" "$REPORT_SNPID"
# The output of this step is a temporary report file with renamed marker IDs and RefMatch and AltMatch allele fasta files
TMP_RENAME=${REPORT_SNPID%????}'_tmp_rename.csv'
MATCH_ALLELES=${REPORT_SNPID%????}'_match.fa'
MATCH_ALLELES_V1=${REPORT_SNPID%????}'_match_v1.fa'
MATCH_ALLELES_V2=${REPORT_SNPID%????}'_match_v2.fa'
MATCH_ALLELES_BLAST=$MATCH_ALLELES
MIXED_MARKER_VERSIONS=false


printf "\n#  4). Remove adapters using cutadapt"
#  -n COUNT, --times COUNT
#                        Remove up to COUNT adapters from each read. Default: 1
#  -O MINLENGTH, --overlap MINLENGTH
#                        Require MINLENGTH overlap between read and adapter for an adapter to be found.
#                        Default: 3
# -a ACCGATCTCGTATGCCGTCTTCTGCTTG
if python3 "$SCRIPTS_DIR/step02_split_match_fasta_by_marker_version_v1.py" "$SNPID_LUT" "$MATCH_ALLELES"; then
    MIXED_MARKER_VERSIONS=true
    printf "\n  # Mixed v1/v2 marker versions detected. Only v1 markers will be checked with cutadapt.\n"
    SPLIT_STATUS=0
else
    SPLIT_STATUS=$?
fi

if [[ $SPLIT_STATUS -eq 2 ]]; then
    printf "\n  # No mixed v1/v2 marker versions detected. Use original cutadapt workflow.\n"
elif [[ $SPLIT_STATUS -ne 0 ]]; then
    printf "\n  # Failed to split match FASTA by marker version.\n"
    exit $SPLIT_STATUS
fi

if [[ "$MIXED_MARKER_VERSIONS" == "true" ]]; then
    V1_FINAL_FASTA=$MATCH_ALLELES_V1
    if [ $DESIGN_LEN -ge $SEQ_LEN ]; then
        printf "\n  # Design length is greater than or equal to sequencing length. No need to run adaptor checking\n"
    else
        printf "\n  # Sequencing length is longer than panel design length, run cutadapt on v1 markers only\n"
        CUTADAPT=${REPORT_SNPID%????}'_match_v1_cutadapt.fa'
        CUT_LOG=${REPORT_SNPID%????}'_match_v1_cutadapt.log'
        CUTADAPT_BIN=${CUTADAPT_BIN:-$(command -v cutadapt)}
        if [[ -z "${CUTADAPT_BIN}" ]]; then
            printf "\n  # cutadapt not found in PATH. Set CUTADAPT_BIN or install cutadapt.\n"
            exit 1
        fi
        if [[ ! -s "$MATCH_ALLELES_V1" ]]; then
            printf "\n  # v1 match allele fasta not found or empty: %s\n" "$MATCH_ALLELES_V1"
            exit 1
        fi
        "$CUTADAPT_BIN" -a ACCGATCTG -e 0.2 -n 1 --overlap 5 -m $DESIGN_LEN -o "$CUTADAPT" "$MATCH_ALLELES_V1" > "$CUT_LOG" 2>&1
        if [[ ! -f "$CUTADAPT" ]]; then
            printf "\n  # cutadapt did not produce output fasta: %s\n" "$CUTADAPT"
            printf "\n  # Check cutadapt log: %s\n" "$CUT_LOG"
            exit 1
        fi
        MATCH=$(grep -c ">" "$MATCH_ALLELES_V1")
        MATCH_CUT=$(grep -c ">" "$CUTADAPT")
        printf "\n    # Number of v1 RefMatch and AltMatch extracted from MADC: $MATCH"
        printf "\n    # Number of v1 RefMatch and AltMatch retained after cutadapt: $MATCH_CUT\n"

        printf "\n#  5). Check if there are duplicate alleles after removing adapters AND update allele sequences and read counts\n"
        printf "  # CUTADAPT file: $CUTADAPT\n"
        printf "  # Temporary rename file: $TMP_RENAME\n"
        python3 "$SCRIPTS_DIR/step03_check_cutadapt_allele_uniqueness_AND_update_tmp_rename_report_v1.1.py" "$CUTADAPT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME"
        CUTADAPT_UNI=${REPORT_SNPID%????}'_match_v1_cutadapt_unique.fa'
        TMP_RENAME_UPDATED=${REPORT_SNPID%????}'_tmp_rename_updatedSeq.csv'
        if test -f "$CUTADAPT_UNI"; then
            V1_FINAL_FASTA=$CUTADAPT_UNI
        else
            V1_FINAL_FASTA=$CUTADAPT
        fi
    fi
    MATCH_ALLELES_BLAST=${REPORT_SNPID%????}'_match_v1cutadapt_v2uncut.fa'
    python3 "$SCRIPTS_DIR/step04_concat_v1_cutadapt_v2_uncut_fasta_v1.py" "$V1_FINAL_FASTA" "$MATCH_ALLELES_V2" "$MATCH_ALLELES_BLAST"
elif [ $DESIGN_LEN -ge $SEQ_LEN ]; then
    printf "\n  # Design length is greater than or equal to sequencing length. No need to run adaptor checking\n"
else
    printf "\n  # Sequencing length is longer than panel design length, run cutadapt\n"
    CUTADAPT=${REPORT_SNPID%????}'_match_cutadapt.fa'
    CUT_LOG=${REPORT_SNPID%????}'_match_cutadapt.log'
    CUTADAPT_BIN=${CUTADAPT_BIN:-$(command -v cutadapt)}
    if [[ -z "${CUTADAPT_BIN}" ]]; then
        printf "\n  # cutadapt not found in PATH. Set CUTADAPT_BIN or install cutadapt.\n"
        exit 1
    fi
    if [[ ! -f "$MATCH_ALLELES" ]]; then
        printf "\n  # Match allele fasta not found: %s\n" "$MATCH_ALLELES"
        exit 1
    fi
    "$CUTADAPT_BIN" -a ACCGATCTG -e 0.2 -n 1 --overlap 5 -m $DESIGN_LEN -o "$CUTADAPT" "$MATCH_ALLELES" > "$CUT_LOG" 2>&1
    if [[ ! -f "$CUTADAPT" ]]; then
        printf "\n  # cutadapt did not produce output fasta: %s\n" "$CUTADAPT"
        printf "\n  # Check cutadapt log: %s\n" "$CUT_LOG"
        exit 1
    fi
    # Some Illumina instruments use a two-color chemistry to encode the four bases. This includes the NextSeq and the NovaSeq.
    # In those instruments, a ‘dark cycle’ (with no detected color) encodes a G.
    # However, dark cycles also occur when sequencing “falls off” the end of the fragment.
    # The read then contains a run of high-quality, but incorrect “G” calls at its 3’ end.
    MATCH=$(grep -c ">" "$MATCH_ALLELES")
    MATCH_CUT=$(grep -c ">" "$CUTADAPT")
    printf "\n    # Number of RefMatch and AltMatch extracted from MADC: $MATCH"
    printf "\n    # Number of RefMatch and AltMatch retained after cutadapt: $MATCH_CUT\n"

    printf "\n#  5). Check if there are duplicate alleles after removing adapters AND update allele sequences and read counts\n"
    printf "  # CUTADAPT file: $CUTADAPT\n"
    printf "  # Temporary rename file: $TMP_RENAME\n"
    python3 "$SCRIPTS_DIR/step03_check_cutadapt_allele_uniqueness_AND_update_tmp_rename_report_v1.1.py" "$CUTADAPT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME"
    CUTADAPT_UNI=${REPORT_SNPID%????}'_match_cutadapt_unique.fa'
    TMP_RENAME_UPDATED=${REPORT_SNPID%????}'_tmp_rename_updatedSeq.csv'
fi


printf "\n#  6a). First, create the BLAST database"
# 1. First, create the BLAST database
makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB" \
            -dbtype nucl \

printf "\n#  6b). BLAST RefMatch and AltMatch against the allele db\n"
# If there are no duplicate alleles, there won't be the a '_match_cutadapt_unique.fa'
# There won't be a '_tmp_rename_updatedSeq.csv' either
# Here, use if else to execute different input files.
if [[ "$MIXED_MARKER_VERSIONS" == "true" ]]; then
    BLAST_QUERY=$MATCH_ALLELES_BLAST
elif test -f "$CUTADAPT"; then
    if test -f "$CUTADAPT_UNI"; then
      BLAST_QUERY=$CUTADAPT_UNI
    else
      BLAST_QUERY=$CUTADAPT
    fi
else
    BLAST_QUERY=$MATCH_ALLELES
fi
BLAST_DBBLAST=$BLAST_QUERY'.alleledb.bn'
blastn -task blastn-short -dust no -soft_masking false -db "$ALLELE_DB_DIR/$ALLELE_DB" -query "$BLAST_QUERY" -out "$BLAST_DBBLAST" -evalue 1e-5 -num_threads 6 -max_target_seqs 15 -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'


printf "\n#  7). Determine status of RefMatch and AltMatch and Assign fixed IDs to them\n"
if test -f "$TMP_RENAME_UPDATED"; then
    python3 "$SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py" "$ALLELE_DB_DIR/$MATCHCNT_LUT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME_UPDATED" "$BLAST_DBBLAST" "$SEQ_LEN" --cov_threshold "$COV" --iden_threshold "$IDEN"
    MADC_CLEANED=${REPORT_SNPID%????}'_rename_updatedSeq.csv'
else
    python3 "$SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py" "$ALLELE_DB_DIR/$MATCHCNT_LUT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME" "$BLAST_DBBLAST" "$SEQ_LEN" --cov_threshold "$COV" --iden_threshold "$IDEN"
    MADC_CLEANED=${REPORT_SNPID%????}'_rename.csv'
fi



printf "\n#  8). Check if there is a new version DB\n"
# If there are new alleles added to the db, a new version of db will be generated
# Otherwise, no new db
VER=$(echo $ALLELE_DB | grep -o 'v[0-9]\{3\}' | cut -c2- | sed 's/^0*//')
NEW_VER=$(printf '%03d' $(($VER+1)))
ALLELE_DB_NEW=$(printf '%s' "$ALLELE_DB" | sed -E "s/v[0-9]{3}/v$NEW_VER/")
if test -f "$ALLELE_DB_DIR/$ALLELE_DB_NEW"; then
    printf "  # New version of db created after adding noval alleles.\n"
    printf "  $ALLELE_DB_DIR/$ALLELE_DB_NEW\n"
    makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB_NEW" -dbtype nucl

    printf "\n#  9). Check if there are duplicates."
    printf "  # If there are duplicates, retain only one allele of the duplicated ones\n"
    #cat $ALLELE_DB_NEW_BLAST | awk '$1!=$5 && $10==100 && $11==100.0' | more
    python3 "$SCRIPTS_DIR/step06_check_db_allele_uniqueness_v1.py" "$ALLELE_DB_DIR/$ALLELE_DB_NEW"

    printf "\n#  10). If there are duplicates in the new version DB, update MADC after removing duplicated alleles in db\n"
    DUP=$ALLELE_DB_DIR/$ALLELE_DB_NEW'.dup.csv'
    if test -f "$DUP"; then
        VER=$(echo $ALLELE_DB | grep -o 'v[0-9]\{3\}' | cut -c2- | sed 's/^0*//')
        NEW_VER_RMDUP=$(printf '%03d' $(($VER+2)))
        ALLELE_DB_NEW_RMDUP=$(printf '%s' "$ALLELE_DB" | sed -E "s/v[0-9]{3}/v$NEW_VER_RMDUP/")
        makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB_NEW_RMDUP" -dbtype nucl
        printf "  # There are duplicate alleles in db. Check if these duplicate alleles are in MADC file.\n"
        python3 "$SCRIPTS_DIR/step06_update_MADC_with_allele_uniqueness_v1.py" "$DUP" "$MADC_CLEANED"
        printf "\n#  11). Add version of the script to the MADC with fixed allele IDs\n"
        if test -f "$TMP_RENAME_UPDATED"; then
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
        if test -f "$TMP_RENAME_UPDATED"; then
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



printf "\n#  12). Tidy up files.\n"
# Extract the directory
DIR_PATH=$(dirname "$REPORT")
HAP_DIR="${DIR_PATH}/matches"
mkdir -p $HAP_DIR
mv "${DIR_PATH}/"*match.fa* "$HAP_DIR/"
rm -f "$TMP_RENAME" "$TMP_RENAME_UPDATED"
printf "\n###### Complete! #######\n"
