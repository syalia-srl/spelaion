#!/bin/bash
# Real-world problem: Convert CSV data exports into JSON for API ingestion.
# Data teams use this to bridge legacy CSV exports to modern JSON APIs
# without installing Python/jq on minimal containers.
#
# Bash features exercised:
#   IFS manipulation, arrays, while-read loop with custom delimiter,
#   here-document, string trimming ${var## }, ${var%% }, parameter expansion,
#   arithmetic, printf, conditional logic

CSV_DATA=$(cat <<'CSVEOF'
name,age,department,salary,active
Alice Chen,34,Engineering,125000,true
Bob Martinez,28,Marketing,85000,true
Carol Williams,41,Engineering,145000,true
David Kim,55,Executive,210000,true
Eve Johnson,23,Marketing,72000,false
Frank Lee,37,Engineering,130000,true
CSVEOF
)

# Read header line to get field names
HEADER=$(echo "$CSV_DATA" | head -1)
IFS=',' read -ra FIELDS <<< "$HEADER"
NUM_FIELDS=${#FIELDS[@]}

echo "Converting CSV with ${NUM_FIELDS} columns: ${HEADER}"
echo ""

# Begin JSON array
echo "["

FIRST=1
ROW_COUNT=0
ACTIVE_COUNT=0
TOTAL_SALARY=0

echo "$CSV_DATA" | tail -n +2 | while IFS=',' read -r name age dept salary active; do
    # Trim whitespace
    name="${name## }"
    name="${name%% }"

    ROW_COUNT=$((ROW_COUNT + 1))

    if [[ "$FIRST" -eq 1 ]]; then
        FIRST=0
    else
        echo "  ,"
    fi

    # Determine type formatting: numbers unquoted, booleans unquoted, strings quoted
    cat <<ROWEOF
  {
    "${FIELDS[0]}": "${name}",
    "${FIELDS[1]}": ${age},
    "${FIELDS[2]}": "${dept}",
    "${FIELDS[3]}": ${salary},
    "${FIELDS[4]}": ${active}
  }
ROWEOF
done

echo "]"

# Summary stats via pipeline
echo ""
echo "--- Conversion Summary ---"
TOTAL_ROWS=$(echo "$CSV_DATA" | tail -n +2 | wc -l | tr -d ' ')
ENG_COUNT=$(echo "$CSV_DATA" | tail -n +2 | awk -F, '$3 == "Engineering"' | wc -l | tr -d ' ')
AVG_SALARY=$(echo "$CSV_DATA" | tail -n +2 | awk -F, '{sum+=$4; n++} END {printf "%d", sum/n}')
MAX_SALARY=$(echo "$CSV_DATA" | tail -n +2 | awk -F, 'BEGIN{m=0} $4>m{m=$4} END{print m}')

echo "Rows converted: ${TOTAL_ROWS}"
echo "Engineers: ${ENG_COUNT}"
echo "Average salary: \$${AVG_SALARY}"
echo "Max salary: \$${MAX_SALARY}"
