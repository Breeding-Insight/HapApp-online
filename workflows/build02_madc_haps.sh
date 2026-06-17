#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'USAGE'
Usage:
  build02_madc_haps.sh \
    --work-dir DIR \
    --scripts-dir DIR \
    --report FILE \
    --snpid-lut FILE \
    --allele-db-base FILE \
    --matchcnt-lut-base FILE \
    [--allele-db-indel FILE --matchcnt-lut-indel FILE] \
    [--dup-tags FILE] \
    [--first-sample-col 17] \
    [--design-len 81] \
    [--seq-len 109] \
    [--cov 90] \
    [--iden 85] \
    [--code-ver v1]
USAGE
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

require_file() {
    local file_path="$1"
    local label="$2"
    [[ -f "$file_path" ]] || die "$label not found: $file_path"
}

require_command() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
}

WORK_DIR=""
SCRIPTS_DIR=""
REPORT=""
SNPID_LUT=""
ALLELE_DB_BASE_PATH=""
MATCHCNT_LUT_BASE_PATH=""
ALLELE_DB_INDEL_PATH=""
MATCHCNT_LUT_INDEL_PATH=""
DUP_TAGS=""
FIRST_SAMPLE_COL=17
DESIGN_LEN=81
SEQ_LEN=109
COV=90
IDEN=85
CODE_VER="v1"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --work-dir) WORK_DIR="$2"; shift 2 ;;
        --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
        --report) REPORT="$2"; shift 2 ;;
        --snpid-lut) SNPID_LUT="$2"; shift 2 ;;
        --allele-db-base) ALLELE_DB_BASE_PATH="$2"; shift 2 ;;
        --matchcnt-lut-base) MATCHCNT_LUT_BASE_PATH="$2"; shift 2 ;;
        --allele-db-indel) ALLELE_DB_INDEL_PATH="$2"; shift 2 ;;
        --matchcnt-lut-indel) MATCHCNT_LUT_INDEL_PATH="$2"; shift 2 ;;
        --dup-tags) DUP_TAGS="$2"; shift 2 ;;
        --first-sample-col) FIRST_SAMPLE_COL="$2"; shift 2 ;;
        --design-len) DESIGN_LEN="$2"; shift 2 ;;
        --seq-len) SEQ_LEN="$2"; shift 2 ;;
        --cov) COV="$2"; shift 2 ;;
        --iden) IDEN="$2"; shift 2 ;;
        --code-ver) CODE_VER="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ -n "$WORK_DIR" ]] || die "Missing --work-dir"
[[ -n "$SCRIPTS_DIR" ]] || die "Missing --scripts-dir"
[[ -n "$REPORT" ]] || die "Missing --report"
[[ -n "$SNPID_LUT" ]] || die "Missing --snpid-lut"
[[ -n "$ALLELE_DB_BASE_PATH" ]] || die "Missing --allele-db-base"
[[ -n "$MATCHCNT_LUT_BASE_PATH" ]] || die "Missing --matchcnt-lut-base"

mkdir -p "$WORK_DIR"

require_file "$REPORT" "MADC report"
require_file "$SNPID_LUT" "SNP ID LUT"
require_file "$ALLELE_DB_BASE_PATH" "Base allele DB FASTA"
require_file "$MATCHCNT_LUT_BASE_PATH" "Base match-count LUT"
[[ -d "$SCRIPTS_DIR" ]] || die "Scripts directory not found: $SCRIPTS_DIR"

if [[ -n "$ALLELE_DB_INDEL_PATH" || -n "$MATCHCNT_LUT_INDEL_PATH" ]]; then
    [[ -n "$ALLELE_DB_INDEL_PATH" && -n "$MATCHCNT_LUT_INDEL_PATH" ]] || die "Provide both indel DB FASTA and indel match-count LUT, or neither"
fi

if [[ -n "$ALLELE_DB_INDEL_PATH" && -f "$ALLELE_DB_INDEL_PATH" && -f "$MATCHCNT_LUT_INDEL_PATH" ]]; then
    ALLELE_DB_PATH="$ALLELE_DB_INDEL_PATH"
    MATCHCNT_LUT_PATH="$MATCHCNT_LUT_INDEL_PATH"
else
    ALLELE_DB_PATH="$ALLELE_DB_BASE_PATH"
    MATCHCNT_LUT_PATH="$MATCHCNT_LUT_BASE_PATH"
fi

SOURCE_ALLELE_DB_DIR="$(cd "$(dirname "$ALLELE_DB_PATH")" && pwd -P)"
PANEL_WORK_DIR="$WORK_DIR/panel_files/$(basename "$SOURCE_ALLELE_DB_DIR")"
mkdir -p "$PANEL_WORK_DIR"

STAGED_ALLELE_DB_PATH="$PANEL_WORK_DIR/$(basename "$ALLELE_DB_PATH")"
if [[ "$(cd "$(dirname "$ALLELE_DB_PATH")" && pwd -P)/$(basename "$ALLELE_DB_PATH")" != "$(cd "$(dirname "$STAGED_ALLELE_DB_PATH")" && pwd -P)/$(basename "$STAGED_ALLELE_DB_PATH")" ]]; then
    cp -p "$ALLELE_DB_PATH" "$STAGED_ALLELE_DB_PATH"
fi
ALLELE_DB_PATH="$STAGED_ALLELE_DB_PATH"

STAGED_MATCHCNT_LUT_PATH="$PANEL_WORK_DIR/$(basename "$MATCHCNT_LUT_PATH")"
if [[ "$(cd "$(dirname "$MATCHCNT_LUT_PATH")" && pwd -P)/$(basename "$MATCHCNT_LUT_PATH")" != "$(cd "$(dirname "$STAGED_MATCHCNT_LUT_PATH")" && pwd -P)/$(basename "$STAGED_MATCHCNT_LUT_PATH")" ]]; then
    cp -p "$MATCHCNT_LUT_PATH" "$STAGED_MATCHCNT_LUT_PATH"
fi
MATCHCNT_LUT_PATH="$STAGED_MATCHCNT_LUT_PATH"

ALLELE_DB_DIR="$(cd "$(dirname "$ALLELE_DB_PATH")" && pwd -P)"
ALLELE_DB="$(basename "$ALLELE_DB_PATH")"
MATCHCNT_LUT="$(basename "$MATCHCNT_LUT_PATH")"

if [[ "$ALLELE_DB" =~ (v[0-9]{3}) ]]; then
    VER_TOKEN="${BASH_REMATCH[1]}"
else
    die "Allele DB filename must contain a version token like v001: $ALLELE_DB"
fi
VER=${VER_TOKEN#v}
VER=$((10#$VER))
NEW_VER=$(printf '%03d' $((VER + 1)))
ALLELE_DB_NEW="${ALLELE_DB/$VER_TOKEN/v$NEW_VER}"

case "$ALLELE_DB" in
    *.fa|*.FA|*.Fa|*.fA|*.fasta|*.FASTA|*.Fasta|*.fna|*.FNA|*.Fna)
        INPUT_DB_STEM="${ALLELE_DB%.*}"
        ;;
    *)
        INPUT_DB_STEM="$ALLELE_DB"
        ;;
esac
NEXT_DB_STEM="${INPUT_DB_STEM/$VER_TOKEN/v$NEW_VER}"
PROCESS_README="$WORK_DIR/${NEXT_DB_STEM}_process.readme"
NO_NEW_ALLELE_README="$WORK_DIR/${INPUT_DB_STEM}_report_noNewAllele.readme"
: > "$PROCESS_README"
exec > >(tee -a "$PROCESS_README") 2>&1

require_command python3
require_command blastn
require_command makeblastdb
if [[ "$SEQ_LEN" -gt "$DESIGN_LEN" ]]; then
    require_command cutadapt
fi

printf "%s\n" "$(date)"
printf "\n--- Scripts, files, and parameters used ---\n"
printf "# Scripts directory: %s\n" "$SCRIPTS_DIR"
printf "# Working directory: %s\n" "$WORK_DIR"
printf "# Report: %s\n" "$REPORT"
printf "# SNP ID LUT: %s\n" "$SNPID_LUT"
printf "# Allele DB input: %s\n" "$ALLELE_DB_PATH"
printf "# Match-count LUT input: %s\n" "$MATCHCNT_LUT_PATH"
printf "# Process README: %s\n" "$PROCESS_README"
printf "# No-new-allele README: %s\n" "$NO_NEW_ALLELE_README"
printf "# First sample column: %s\n" "$FIRST_SAMPLE_COL"
printf "# Panel design length: %s\n" "$DESIGN_LEN"
printf "# Sequencing length: %s\n" "$SEQ_LEN"
printf "# BLAST filtering thresholds: %s%% coverage, %s%% identity\n" "$COV" "$IDEN"

printf "\n# 1). Update snpIDs to Chr_00xxxxxxx format in MADC\n"
python3 "$SCRIPTS_DIR/step00_madc_update_snpID_v1.1.py" "$SNPID_LUT" "$REPORT"
REPORT_SNPID=${REPORT%????}'_snpID.csv'

printf "\n# 2). Remove duplicate tags if provided or derivable\n"
DUP_TAGS_DEFAULT=${REPORT%????}'_dupTags_to_remove.txt'
shopt -s nullglob
dup_cluster_candidates=( "${REPORT%????}"_snpID_ref_alt_amplicons.fa.f*bp_rev_"${SEQ_LEN}"bp_sfetch_ref_only_dupTag_cluster_nonSelf.tsv )
shopt -u nullglob

if [[ -z "$DUP_TAGS" && -f "$DUP_TAGS_DEFAULT" ]]; then
    DUP_TAGS="$DUP_TAGS_DEFAULT"
    printf "  # Use existing duplicate-tags file: %s\n" "$DUP_TAGS"
elif [[ -z "$DUP_TAGS" && ${#dup_cluster_candidates[@]} -eq 1 ]]; then
    DUP_TAG_CLUSTER="${dup_cluster_candidates[0]}"
    printf "  # Derive duplicate tags from build01 cluster file: %s\n" "$DUP_TAG_CLUSTER"
    awk -F '\t' 'NF >= 2 { split($2, a, "|"); print a[1] }' "$DUP_TAG_CLUSTER" | sort -u > "$DUP_TAGS_DEFAULT"
    if [[ -s "$DUP_TAGS_DEFAULT" ]]; then
        DUP_TAGS="$DUP_TAGS_DEFAULT"
        printf "  # Derived duplicate-tags file: %s\n" "$DUP_TAGS"
    else
        printf "  # Duplicate-tag cluster file is empty. Skipping duplicate-tag removal.\n"
    fi
elif [[ -z "$DUP_TAGS" && ${#dup_cluster_candidates[@]} -gt 1 ]]; then
    printf "  # Multiple build01 duplicate-tag cluster files found. Set --dup-tags explicitly.\n"
    for dup_cluster in "${dup_cluster_candidates[@]}"; do
        printf "    - %s\n" "$dup_cluster"
    done
    exit 1
fi

if [[ -z "$DUP_TAGS" ]]; then
    printf "  # No duplicate-tags file provided or derived. Skipping duplicate-tag removal.\n"
elif [[ ! -f "$DUP_TAGS" ]]; then
    die "Duplicate-tags file not found: $DUP_TAGS"
else
    printf "  # Duplicate-tags file: %s\n" "$DUP_TAGS"
    REPORT_SNPID_RMDUP=${REPORT_SNPID%????}'_rmDup.csv'
    python3 "$SCRIPTS_DIR/step00_rm_dupTag_closeTag_rawMADC_v1.py" "$DUP_TAGS" "$REPORT_SNPID" "$REPORT_SNPID_RMDUP"
    printf "  # SNPID-updated MADC file with duplicate tags removed: %s\n" "$REPORT_SNPID_RMDUP"
    REPORT_SNPID="$REPORT_SNPID_RMDUP"
fi

printf "\n# 3). Check duplicate alleles in MADC\n"
python3 "$SCRIPTS_DIR/step00_check_allele_uniqueness.py" "$REPORT_SNPID" "$FIRST_SAMPLE_COL"
REPORT_SNPID_DUP=${REPORT_SNPID%????}'_dup.csv'
if [[ -f "$REPORT_SNPID_DUP" ]]; then
    printf "  # Duplicate microhaplotypes found. Review output and rerun after resolving duplicates.\n"
    exit 0
else
    printf "  # No duplicates found in MADC file\n"
fi

printf "\n# 4). Filter missing data and extract RefMatch/AltMatch FASTA\n"
python3 "$SCRIPTS_DIR/step01_filter_missing_AND_ext_matchAlleles_from_madc_v1.py" "$REPORT_SNPID"
TMP_RENAME=${REPORT_SNPID%????}'_tmp_rename.csv'
TMP_RENAME_UPDATED=${REPORT_SNPID%????}'_tmp_rename_updatedSeq.csv'
MATCH_ALLELES=${REPORT_SNPID%????}'_match.fa'
MATCH_ALLELES_V1=${REPORT_SNPID%????}'_match_v1.fa'
MATCH_ALLELES_V2=${REPORT_SNPID%????}'_match_v2.fa'
MATCH_ALLELES_BLAST=$MATCH_ALLELES
MIXED_MARKER_VERSIONS=false
CUTADAPT=""
CUTADAPT_UNI=""

printf "\n# 5). Remove adapters with cutadapt when needed\n"
set +e
python3 "$SCRIPTS_DIR/step02_split_match_fasta_by_marker_version_v1.py" "$SNPID_LUT" "$MATCH_ALLELES"
SPLIT_STATUS=$?
set -e

if [[ $SPLIT_STATUS -eq 0 ]]; then
    MIXED_MARKER_VERSIONS=true
    printf "  # Mixed v1/v2 marker versions detected. Only v1 markers will be checked with cutadapt.\n"
elif [[ $SPLIT_STATUS -eq 2 ]]; then
    printf "  # No mixed v1/v2 marker versions detected. Use original cutadapt workflow.\n"
else
    die "Failed to split match FASTA by marker version. Exit code: $SPLIT_STATUS"
fi

if [[ "$MIXED_MARKER_VERSIONS" == "true" ]]; then
    V1_FINAL_FASTA=$MATCH_ALLELES_V1
    if [[ "$DESIGN_LEN" -ge "$SEQ_LEN" ]]; then
        printf "  # Design length is greater than or equal to sequencing length. No adapter checking needed.\n"
    else
        CUTADAPT=${REPORT_SNPID%????}'_match_v1_cutadapt.fa'
        CUT_LOG=${REPORT_SNPID%????}'_match_v1_cutadapt.log'
        [[ -s "$MATCH_ALLELES_V1" ]] || die "v1 match allele FASTA not found or empty: $MATCH_ALLELES_V1"
        cutadapt -a ACCGATCTG -e 0.2 -n 1 --overlap 5 -m "$DESIGN_LEN" -o "$CUTADAPT" "$MATCH_ALLELES_V1" > "$CUT_LOG" 2>&1
        [[ -f "$CUTADAPT" ]] || die "cutadapt did not produce output FASTA: $CUTADAPT. Check $CUT_LOG"
        MATCH=$(grep -c ">" "$MATCH_ALLELES_V1" || true)
        MATCH_CUT=$(grep -c ">" "$CUTADAPT" || true)
        printf "    # Number of v1 RefMatch and AltMatch extracted from MADC: %s\n" "$MATCH"
        printf "    # Number of v1 RefMatch and AltMatch retained after cutadapt: %s\n" "$MATCH_CUT"

        printf "\n# 6). Check duplicate alleles after cutadapt and update temporary report\n"
        python3 "$SCRIPTS_DIR/step03_check_cutadapt_allele_uniqueness_AND_update_tmp_rename_report_v1.1.py" "$CUTADAPT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME"
        CUTADAPT_UNI=${REPORT_SNPID%????}'_match_v1_cutadapt_unique.fa'
        if [[ -f "$CUTADAPT_UNI" ]]; then
            V1_FINAL_FASTA=$CUTADAPT_UNI
        else
            V1_FINAL_FASTA=$CUTADAPT
        fi
    fi
    MATCH_ALLELES_BLAST=${REPORT_SNPID%????}'_match_v1cutadapt_v2uncut.fa'
    python3 "$SCRIPTS_DIR/step04_concat_v1_cutadapt_v2_uncut_fasta_v1.py" "$V1_FINAL_FASTA" "$MATCH_ALLELES_V2" "$MATCH_ALLELES_BLAST"
elif [[ "$DESIGN_LEN" -ge "$SEQ_LEN" ]]; then
    printf "  # Design length is greater than or equal to sequencing length. No adapter checking needed.\n"
else
    CUTADAPT=${REPORT_SNPID%????}'_match_cutadapt.fa'
    CUT_LOG=${REPORT_SNPID%????}'_match_cutadapt.log'
    [[ -f "$MATCH_ALLELES" ]] || die "Match allele FASTA not found: $MATCH_ALLELES"
    cutadapt -a ACCGATCTG -e 0.2 -n 1 --overlap 5 -m "$DESIGN_LEN" -o "$CUTADAPT" "$MATCH_ALLELES" > "$CUT_LOG" 2>&1
    [[ -f "$CUTADAPT" ]] || die "cutadapt did not produce output FASTA: $CUTADAPT. Check $CUT_LOG"
    MATCH=$(grep -c ">" "$MATCH_ALLELES" || true)
    MATCH_CUT=$(grep -c ">" "$CUTADAPT" || true)
    printf "    # Number of RefMatch and AltMatch extracted from MADC: %s\n" "$MATCH"
    printf "    # Number of RefMatch and AltMatch retained after cutadapt: %s\n" "$MATCH_CUT"

    printf "\n# 6). Check duplicate alleles after cutadapt and update temporary report\n"
    python3 "$SCRIPTS_DIR/step03_check_cutadapt_allele_uniqueness_AND_update_tmp_rename_report_v1.1.py" "$CUTADAPT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME"
    CUTADAPT_UNI=${REPORT_SNPID%????}'_match_cutadapt_unique.fa'
fi

printf "\n# 7). Create the BLAST database\n"
makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB" -dbtype nucl

printf "\n# 8). BLAST RefMatch and AltMatch against the allele DB\n"
if [[ "$MIXED_MARKER_VERSIONS" == "true" ]]; then
    BLAST_QUERY=$MATCH_ALLELES_BLAST
elif [[ -n "$CUTADAPT" && -f "$CUTADAPT" ]]; then
    if [[ -n "$CUTADAPT_UNI" && -f "$CUTADAPT_UNI" ]]; then
        BLAST_QUERY=$CUTADAPT_UNI
    else
        BLAST_QUERY=$CUTADAPT
    fi
else
    BLAST_QUERY=$MATCH_ALLELES
fi
BLAST_DBBLAST=$BLAST_QUERY'.alleledb.bn'
blastn -task blastn-short -dust no -soft_masking false \
    -db "$ALLELE_DB_DIR/$ALLELE_DB" \
    -query "$BLAST_QUERY" \
    -out "$BLAST_DBBLAST" \
    -evalue 1e-5 -num_threads 6 -max_target_seqs 15 \
    -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'

printf "\n# 9). Determine RefMatch/AltMatch status and assign fixed IDs\n"
if [[ -f "$TMP_RENAME_UPDATED" ]]; then
    python3 "$SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py" "$ALLELE_DB_DIR/$MATCHCNT_LUT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME_UPDATED" "$BLAST_DBBLAST" "$SEQ_LEN" --cov_threshold "$COV" --iden_threshold "$IDEN"
    MADC_CLEANED=${REPORT_SNPID%????}'_rename_updatedSeq.csv'
else
    python3 "$SCRIPTS_DIR/step05_parse_madc_allele81bp_blastn_v1.py" "$ALLELE_DB_DIR/$MATCHCNT_LUT" "$ALLELE_DB_DIR/$ALLELE_DB" "$TMP_RENAME" "$BLAST_DBBLAST" "$SEQ_LEN" --cov_threshold "$COV" --iden_threshold "$IDEN"
    MADC_CLEANED=${REPORT_SNPID%????}'_rename.csv'
fi

printf "\n# 10). Check if a new DB version was created\n"

if [[ -f "$ALLELE_DB_DIR/$ALLELE_DB_NEW" ]]; then
    printf "  # New version of DB created after adding novel alleles: %s\n" "$ALLELE_DB_DIR/$ALLELE_DB_NEW"
    makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB_NEW" -dbtype nucl

    printf "\n# 11). Check duplicate alleles in the new DB\n"
    python3 "$SCRIPTS_DIR/step06_check_db_allele_uniqueness_v1.py" "$ALLELE_DB_DIR/$ALLELE_DB_NEW"

    printf "\n# 12). Update MADC if duplicate alleles were removed from DB\n"
    DUP=$ALLELE_DB_DIR/$ALLELE_DB_NEW'.dup.csv'
    if [[ -f "$DUP" ]]; then
        NEW_VER_RMDUP=$(printf '%03d' $((VER + 2)))
        ALLELE_DB_NEW_RMDUP=$(printf '%s' "$ALLELE_DB" | sed -E "s/v[0-9]{3}/v$NEW_VER_RMDUP/")
        makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB_NEW_RMDUP" -dbtype nucl
        python3 "$SCRIPTS_DIR/step06_update_MADC_with_allele_uniqueness_v1.py" "$DUP" "$MADC_CLEANED"
        if [[ -f "$TMP_RENAME_UPDATED" ]]; then
            MADC_CLEANED_RMDUP=${REPORT_SNPID%????}'_rename_updatedSeq_rmDup.csv'
            MADC_CLEANED_RMDUP_VER=${REPORT_SNPID%????}'_rename_updatedSeq_rmDup_'"$CODE_VER"'.csv'
        else
            MADC_CLEANED_RMDUP=${REPORT_SNPID%????}'_rename_rmDup.csv'
            MADC_CLEANED_RMDUP_VER=${REPORT_SNPID%????}'_rename_rmDup_'"$CODE_VER"'.csv'
        fi
        awk -v val="$CODE_VER" 'NR==1{print "Code_version," $0} NR>1{print val "," $0}' "$MADC_CLEANED_RMDUP" > "$MADC_CLEANED_RMDUP_VER"
    else
        printf "  # No duplicate alleles found in microhap DB\n"
        if [[ -f "$TMP_RENAME_UPDATED" ]]; then
            MADC_CLEANED_VER=${REPORT_SNPID%????}'_rename_updatedSeq_'"$CODE_VER"'.csv'
        else
            MADC_CLEANED_VER=${REPORT_SNPID%????}'_rename_'"$CODE_VER"'.csv'
        fi
        awk -v val="$CODE_VER" 'NR==1{print "Code_version," $0} NR>1{print val "," $0}' "$MADC_CLEANED" > "$MADC_CLEANED_VER"
        printf "  # Code version added as first column of output MADC.\n"
    fi
else
    printf "  # No new alleles found, therefore no new DB was generated.\n"
    mv "$PROCESS_README" "$NO_NEW_ALLELE_README"
fi

printf "\n# 13). Tidy match FASTA files\n"
DIR_PATH=$(dirname "$REPORT")
HAP_DIR="${DIR_PATH}/matches"
mkdir -p "$HAP_DIR"
shopt -s nullglob
match_files=( "$DIR_PATH"/*match.fa* )
if [[ ${#match_files[@]} -gt 0 ]]; then
    mv "${match_files[@]}" "$HAP_DIR/"
fi
shopt -u nullglob
rm -f "$TMP_RENAME" "$TMP_RENAME_UPDATED"
printf "\n###### Complete! #######\n"
