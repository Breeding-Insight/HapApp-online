#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'USAGE'
Usage:
  build01_ref_alt_core_db.sh \
    --work-dir DIR \
    --scripts-dir DIR \
    --probe-file FILE \
    --chr-len FILE \
    --ref-genome FILE \
    --report FILE \
    [--output-prefix core_allele_db_v001] \
    [--ref-len 109] \
    [--flank-len 150]
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

ensure_esl_index() {
    local fasta_file="$1"
    if [[ ! -f "${fasta_file}.ssi" ]]; then
        printf '[INFO] Building esl-sfetch index for %s\n' "$fasta_file"
        esl-sfetch --index "$fasta_file"
    fi
}

require_fasta_output() {
    local fasta_file="$1"
    local step_label="$2"
    [[ -s "$fasta_file" ]] || die "$step_label did not create output FASTA: $fasta_file"
    grep -q '^>' "$fasta_file" || die "$step_label produced a non-FASTA output file: $fasta_file"
}

WORK_DIR=""
SCRIPTS_DIR=""
PROBE_FILE=""
CHR_LEN=""
REF_GENOME=""
REPORT=""
OUTPUT_PREFIX="core_allele_db_v001"
REF_LEN=109
FLANK_LEN=150

while [[ $# -gt 0 ]]; do
    case "$1" in
        --work-dir) WORK_DIR="$2"; shift 2 ;;
        --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
        --probe-file) PROBE_FILE="$2"; shift 2 ;;
        --chr-len) CHR_LEN="$2"; shift 2 ;;
        --ref-genome) REF_GENOME="$2"; shift 2 ;;
        --report) REPORT="$2"; shift 2 ;;
        --output-prefix) OUTPUT_PREFIX="$2"; shift 2 ;;
        --ref-len) REF_LEN="$2"; shift 2 ;;
        --flank-len) FLANK_LEN="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ -n "$WORK_DIR" ]] || die "Missing --work-dir"
[[ -n "$SCRIPTS_DIR" ]] || die "Missing --scripts-dir"
[[ -n "$PROBE_FILE" ]] || die "Missing --probe-file"
[[ -n "$CHR_LEN" ]] || die "Missing --chr-len"
[[ -n "$REF_GENOME" ]] || die "Missing --ref-genome"
[[ -n "$REPORT" ]] || die "Missing --report"

OUTPUT_PREFIX="${OUTPUT_PREFIX%.fa}"
[[ "$OUTPUT_PREFIX" != */* ]] || die "--output-prefix must be a basename, not a path"
[[ "$OUTPUT_PREFIX" =~ v[0-9]{3} ]] || die "--output-prefix must contain a version token like v001"

mkdir -p "$WORK_DIR"
PROCESS_README="$WORK_DIR/core_ref_alt_db_process.readme"
: > "$PROCESS_README"
exec > >(tee -a "$PROCESS_README") 2>&1

require_command python3
require_command blastn
require_command makeblastdb
require_command esl-sfetch
require_command seqkit
require_command mmseqs

require_file "$PROBE_FILE" "Probe design file"
require_file "$CHR_LEN" "Chromosome length file"
require_file "$REF_GENOME" "Reference genome FASTA"
require_file "$REPORT" "MADC report"
[[ -d "$SCRIPTS_DIR" ]] || die "Scripts directory not found: $SCRIPTS_DIR"

ALLELE_DB_DIR="$WORK_DIR"
ALLELE_DB_BASE="${OUTPUT_PREFIX}.fa"
MATCH_CNT_BASE="${OUTPUT_PREFIX}_matchCnt_lut.txt"
ALLELE_DB_INDEL="${OUTPUT_PREFIX}_indelsAdded.fa"
MATCH_CNT_INDEL="${OUTPUT_PREFIX}_indelsAdded_matchCnt_lut.txt"
ALLELE_DB="$ALLELE_DB_BASE"
MATCH_CNT="$MATCH_CNT_BASE"

printf "%s\n" "$(date)"
printf "\n--- Scripts, files, and parameters used ---\n"
printf "# Scripts directory: %s\n" "$SCRIPTS_DIR"
printf "# Working directory: %s\n" "$WORK_DIR"
printf "# Probe design file: %s\n" "$PROBE_FILE"
printf "# Chromosome lengths: %s\n" "$CHR_LEN"
printf "# Reference genome: %s\n" "$REF_GENOME"
printf "# MADC report: %s\n" "$REPORT"
printf "# Output prefix: %s\n" "$OUTPUT_PREFIX"
printf "# Ref length: %s\n" "$REF_LEN"
printf "# Flank length: %s\n" "$FLANK_LEN"

printf "\n# 1). Prepare marker ID LUT\n"
python3 "$SCRIPTS_DIR/db00_prep_lut_from_probeDesign.py" "$PROBE_FILE" --madc "$REPORT"
SNPID_LUT=${PROBE_FILE%????}'_snpID_lut.csv'

INDEL_COUNT=$(python3 - "$SNPID_LUT" <<'PY'
import csv
import sys

with open(sys.argv[1], "r", encoding="utf-8", newline="") as inp:
    reader = csv.DictReader(inp)
    count = sum(1 for row in reader if (row.get("Type") or "").strip().lower() == "indel")
print(count)
PY
)

if [[ "${INDEL_COUNT:-0}" -gt 0 ]]; then
    ALLELE_DB="$ALLELE_DB_INDEL"
    MATCH_CNT="$MATCH_CNT_INDEL"
    printf "[INFO] Indel loci detected in LUT: %s. Final DB outputs will use the _indelsAdded suffix.\n" "$INDEL_COUNT"
else
    printf "[INFO] No indel loci detected in LUT. Final DB outputs will keep the base filenames.\n"
fi

printf "\n# 2). Update snpIDs in DArTag report\n"
python3 "$SCRIPTS_DIR/db02_update_snpID_in_madc_v1.py" "$SNPID_LUT" "$REPORT"
REPORT_ID=${REPORT%????}'_snpID.csv'
REPORT_ID_MATCHCNT=${REPORT%????}'_snpID_matchCnt_lut.txt'

printf "\n# 3). Prepare sfetch coordinates of flanking sequences\n"
python3 "$SCRIPTS_DIR/db01_get_reference_sfetch_keys_from_snpID_lut_v1.py" \
    --lut "$SNPID_LUT" \
    --chr_len "$CHR_LEN" \
    --flankBP "$FLANK_LEN" \
    --madc "$REPORT_ID"
FLANK_SFETCH=${SNPID_LUT%????}'_f'"$FLANK_LEN"'bp_sfetchKeys.txt'

printf "\n# 4). Fetch flanking sequences\n"
FLANK_SEQ=${SNPID_LUT%????}'_f'"$FLANK_LEN"'bp_sfetchKeys.fa'
ensure_esl_index "$REF_GENOME"
esl-sfetch -Cf "$REF_GENOME" "$FLANK_SFETCH" > "$FLANK_SEQ"
require_fasta_output "$FLANK_SEQ" "Step 4"

printf "\n# 5). Prepare Ref and Alt allele sequences from flanking sequences\n"
python3 "$SCRIPTS_DIR/db01_prep_ref_alt_flankSeq_from_lut_v1.py" \
    --snpID_lut "$SNPID_LUT" \
    --flankSeq "$FLANK_SEQ" \
    --flank_len "$FLANK_LEN"
REF_ALT_FLANK=${SNPID_LUT%????}'_f'"$FLANK_LEN"'bp_sfetchKeys_ref_alt.fa'
makeblastdb -in "$REF_ALT_FLANK" -dbtype nucl

printf "\n# 6). Extract Ref and Alt amplicon sequences from MADC report\n"
python3 "$SCRIPTS_DIR/db03_ext_ref_alt_amp_from_madc_v1.py" "$REPORT_ID"
REF_ALT=${REPORT_ID%????}'_ref_alt_amplicons.fa'

printf "\n# 7). BLAST Ref and Alt amplicons to flanking sequences\n"
REF_ALT_BLAST=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp.bn'
blastn -task blastn-short -dust no -soft_masking false \
    -db "$REF_ALT_FLANK" \
    -query "$REF_ALT" \
    -out "$REF_ALT_BLAST" \
    -evalue 1e-5 -num_threads 6 -max_target_seqs 10 \
    -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'

printf "\n# 8). Determine alignment orientation and update flanking sequences\n"
python3 "$SCRIPTS_DIR/db05_determine_alleleOri_from_blast_AND_update_f180bp_v1.py" "$REF_ALT_BLAST" "$REF_ALT_FLANK"

printf "\n# 9). Rerun BLAST against updated flanking sequences\n"
REF_ALT_FLANK_REV=${REF_ALT_FLANK%???}'_rev.fa'
makeblastdb -in "$REF_ALT_FLANK_REV" -dbtype nucl
REF_ALT_BLAST_REV=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev.bn'
blastn -task blastn-short -dust no -soft_masking false \
    -db "$REF_ALT_FLANK_REV" \
    -query "$REF_ALT" \
    -out "$REF_ALT_BLAST_REV" \
    -evalue 1e-5 -num_threads 6 -max_target_seqs 10 \
    -outfmt '6 qseqid qlen qstart qend sseqid slen sstart send length qcovs pident evalue'

printf "\n# 10). Generate sfetch keys for amplicons\n"
python3 "$SCRIPTS_DIR/db07_generate_ref_alt_sfetch_keys_from_blast_v1.1.py" "$SNPID_LUT" "$REF_ALT_BLAST_REV" "$REF_LEN"

printf "\n# 11). Fetch amplicon sequences from flanking sequences\n"
esl-sfetch --index "$REF_ALT_FLANK_REV"
REF_ALT_BLAST_REV_SFETCH=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetchKeys.txt'
SFETCH_FA=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch.fa'
esl-sfetch -Cf "$REF_ALT_FLANK_REV" "$REF_ALT_BLAST_REV_SFETCH" > "$SFETCH_FA"
require_fasta_output "$SFETCH_FA" "Step 11"

printf "\n# 12). Check highly similar Ref sequences from different marker loci\n"
SFETCH_FA_REF=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only.fa'
seqkit grep -nrp '\|Ref_0001\b' "$SFETCH_FA" > "$SFETCH_FA_REF"

MMSEQS_OUT=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only_dupTag'
TMP="$WORK_DIR/mmseqs_tmp"
mmseqs easy-linclust \
    "$SFETCH_FA_REF" \
    "$MMSEQS_OUT" \
    "$TMP" \
    --min-seq-id 0.95 -c 0.99 --cov-mode 2 -v 0 --threads 8

MMSEQS_OUT_ALLSEQS=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only_dupTag_all_seqs.fasta'
MMSEQS_OUT_REPSEQS=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only_dupTag_rep_seq.fasta'
MMSEQS_OUT_CLUSTER=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only_dupTag_cluster.tsv'
MMSEQS_OUT_CLUSTER_NONSELF=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_ref_only_dupTag_cluster_nonSelf.tsv'
awk '$1!=$2' "$MMSEQS_OUT_CLUSTER" > "$MMSEQS_OUT_CLUSTER_NONSELF"

if [[ ! -s "$MMSEQS_OUT_CLUSTER_NONSELF" ]]; then
    printf "  # No non-self duplicate-tag clusters detected.\n"
    rm -f "$MMSEQS_OUT_CLUSTER_NONSELF"
    FINAL_FASTA_SRC="$SFETCH_FA"
    FINAL_MATCHCNT_SRC="$REPORT_ID_MATCHCNT"
else
    printf "  # Non-self duplicate-tag clusters detected. Removing duplicate markers from final outputs.\n"
    python3 "$SCRIPTS_DIR/db09_rm_dupTags_from_LUT_and_db_v001.py" "$SNPID_LUT" "$MMSEQS_OUT_CLUSTER_NONSELF"
    python3 "$SCRIPTS_DIR/db09_rm_dupTags_from_LUT_and_db_v001.py" "$REPORT_ID_MATCHCNT" "$MMSEQS_OUT_CLUSTER_NONSELF"
    python3 "$SCRIPTS_DIR/db09_rm_dupTags_from_LUT_and_db_v001.py" "$SFETCH_FA" "$MMSEQS_OUT_CLUSTER_NONSELF"
    FINAL_FASTA_SRC=${REPORT%????}'_snpID_ref_alt_amplicons.fa.f'"$FLANK_LEN"'bp_rev_'"$REF_LEN"'bp_sfetch_rmDupTag.fa'
    FINAL_MATCHCNT_SRC=${REPORT%????}'_snpID_matchCnt_lut_rmDupTag.txt'
fi

printf "\n# 13). Finalize DB files\n"
if [[ "${INDEL_COUNT:-0}" -gt 0 ]]; then
    printf "  # Indel loci detected. Add missing baseline indel alleles if needed.\n"
    python3 "$SCRIPTS_DIR/db10_add_missing_indels_to_db.py" \
        --lut "$SNPID_LUT" \
        --probe "$PROBE_FILE" \
        --amplicons "$REF_ALT" \
        --input_fasta "$FINAL_FASTA_SRC" \
        --input_matchcnt "$FINAL_MATCHCNT_SRC" \
        --output_fasta "$ALLELE_DB_DIR/$ALLELE_DB" \
        --output_matchcnt "$ALLELE_DB_DIR/$MATCH_CNT" \
        --ref_len "$REF_LEN"
else
    printf "  # No indel loci detected. Copy finalized FASTA and match-count LUT as-is.\n"
    cp "$FINAL_FASTA_SRC" "$ALLELE_DB_DIR/$ALLELE_DB"
    cp "$FINAL_MATCHCNT_SRC" "$ALLELE_DB_DIR/$MATCH_CNT"
fi

printf "\n# 14). Make final BLAST DB\n"
makeblastdb -in "$ALLELE_DB_DIR/$ALLELE_DB" -dbtype nucl

rm -rf "$TMP"
rm -f "$MMSEQS_OUT_ALLSEQS"
rm -f "$MMSEQS_OUT_REPSEQS"
printf "\n###### Complete! #######\n"
