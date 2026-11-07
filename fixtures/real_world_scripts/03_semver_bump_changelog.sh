#!/bin/bash
# Real-world problem: Parse the current semver tag, bump it according to
# conventional commit messages, extract changelog entries. Used in release
# automation pipelines.
#
# Bash features exercised:
#   IFS splitting, arrays, string substitution ${var//pat/rep}, parameter
#   expansion with substring ${var:offset:len}, arithmetic, while-read loop,
#   case statement, here-document, [[ =~ ]] regex match

CURRENT_VERSION="2.14.7"

# Simulated git log (normally: git log v${CURRENT_VERSION}..HEAD --oneline)
COMMIT_LOG=$(cat <<'COMMITS'
abc1234 feat: add batch processing endpoint
def5678 fix: correct null pointer in user lookup
ghi9012 feat: implement webhook retry logic
jkl3456 fix: handle timezone edge case in scheduler
mno7890 docs: update API reference for v3
pqr1234 feat!: redesign authentication flow
stu5678 chore: update dependencies
vwx9012 fix: memory leak in connection pool
COMMITS
)

# Parse current version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
echo "Current version: ${MAJOR}.${MINOR}.${PATCH}"

# Analyze commits for bump type
HAS_BREAKING=0
HAS_FEAT=0
HAS_FIX=0
FEAT_COUNT=0
FIX_COUNT=0

declare -a FEATURES
declare -a FIXES
declare -a OTHERS

while IFS= read -r line; do
    hash="${line%% *}"
    msg="${line#* }"

    if [[ "$msg" =~ ^feat!: ]] || [[ "$msg" =~ BREAKING ]]; then
        HAS_BREAKING=1
        FEATURES+=("${hash:0:7} ${msg}")
        FEAT_COUNT=$((FEAT_COUNT + 1))
    elif [[ "$msg" =~ ^feat: ]]; then
        HAS_FEAT=1
        FEATURES+=("${hash:0:7} ${msg}")
        FEAT_COUNT=$((FEAT_COUNT + 1))
    elif [[ "$msg" =~ ^fix: ]]; then
        HAS_FIX=1
        FIXES+=("${hash:0:7} ${msg}")
        FIX_COUNT=$((FIX_COUNT + 1))
    else
        OTHERS+=("${hash:0:7} ${msg}")
    fi
done <<< "$COMMIT_LOG"

# Determine bump type
if [[ $HAS_BREAKING -eq 1 ]]; then
    BUMP="major"
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
elif [[ $HAS_FEAT -eq 1 ]]; then
    BUMP="minor"
    MINOR=$((MINOR + 1))
    PATCH=0
elif [[ $HAS_FIX -eq 1 ]]; then
    BUMP="patch"
    PATCH=$((PATCH + 1))
else
    BUMP="none"
fi

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

echo "Bump type: ${BUMP}"
echo "New version: ${NEW_VERSION}"
echo ""

# Generate changelog
TOTAL=$((FEAT_COUNT + FIX_COUNT + ${#OTHERS[@]}))
echo "## [${NEW_VERSION}] - $(date +%Y-%m-%d 2>/dev/null || echo '2024-03-15')"
echo ""

if [[ ${#FEATURES[@]} -gt 0 ]]; then
    echo "### Features (${FEAT_COUNT})"
    for entry in "${FEATURES[@]}"; do
        echo "- ${entry}"
    done
    echo ""
fi

if [[ ${#FIXES[@]} -gt 0 ]]; then
    echo "### Bug Fixes (${FIX_COUNT})"
    for entry in "${FIXES[@]}"; do
        echo "- ${entry}"
    done
    echo ""
fi

if [[ ${#OTHERS[@]} -gt 0 ]]; then
    echo "### Other (${#OTHERS[@]})"
    for entry in "${OTHERS[@]}"; do
        echo "- ${entry}"
    done
    echo ""
fi

echo "---"
echo "Total commits: ${TOTAL} | ${CURRENT_VERSION} -> ${NEW_VERSION}"
