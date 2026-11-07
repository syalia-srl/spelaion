#!/bin/bash
# Real-world problem: Generate formatted release notes from git log entries,
# grouping by category, computing contributor stats, and producing both
# human-readable and machine-readable output. Used by release managers.
#
# Bash features exercised:
#   associative arrays (multiple), indexed arrays, while-read with IFS,
#   [[ =~ ]] regex with capture groups (BASH_REMATCH), case statement,
#   parameter expansion (substring, length, default), printf, here-document

# Simulated git log entries: "hash|author|message"
GIT_LOG=$(cat <<'GITEOF'
a1b2c3d|Alice Chen|feat(api): add pagination to user list endpoint
d4e5f6a|Bob Kim|fix(auth): handle expired refresh tokens gracefully
b7c8d9e|Alice Chen|feat(api): implement rate limiting middleware
e1f2a3b|Carol Wu|fix(db): resolve N+1 query in order lookups
c4d5e6f|Bob Kim|docs(api): update swagger spec for v2 endpoints
f7a8b9c|David Lee|feat(ui): add dark mode toggle component
a2b3c4d|Alice Chen|perf(db): add composite index on orders table
d5e6f7a|Carol Wu|refactor(auth): extract token validation to service
b8c9d1e|Eve Park|fix(api): correct status code for duplicate entries
e2f3a4b|David Lee|chore(deps): bump lodash from 4.17.20 to 4.17.21
GITEOF
)

PROJECT_NAME="${PROJECT_NAME:-myproject}"
VERSION="${RELEASE_VERSION:-3.5.0}"

# Category display labels
declare -A CATEGORY_LABELS
CATEGORY_LABELS[feat]="Features"
CATEGORY_LABELS[fix]="Bug Fixes"
CATEGORY_LABELS[perf]="Performance"
CATEGORY_LABELS[refactor]="Refactoring"
CATEGORY_LABELS[docs]="Documentation"
CATEGORY_LABELS[chore]="Maintenance"

# Regex pattern for conventional commits: type(scope): description
COMMIT_PAT='^([a-z]+)[(]([^)]+)[)]: (.+)'

# Accumulate entries with a separator for later processing
# Format: "type::formatted_entry;"
ALL_ENTRIES=
TOTAL_COMMITS=0

echo "$GIT_LOG" | while IFS='|' read -r hash author message; do
    [[ -z "$hash" ]] && continue
    TOTAL_COMMITS=$((TOTAL_COMMITS + 1))

    # Parse conventional commit
    if [[ "$message" =~ $COMMIT_PAT ]]; then
        type="${BASH_REMATCH[1]}"
        scope="${BASH_REMATCH[2]}"
        desc="${BASH_REMATCH[3]}"
    else
        type="other"
        scope=
        desc="$message"
    fi

    # Build formatted entry
    short_hash="${hash:0:7}"
    entry="- **${scope}**: ${desc} (${short_hash}) -- ${author}"

    # Accumulate with separator
    ALL_ENTRIES="${ALL_ENTRIES}${type}::${entry};"
done

# Output release notes
echo "# ${PROJECT_NAME} v${VERSION} Release Notes"
echo ""

# Display categories in order
for cat_type in feat fix perf refactor docs chore; do
    # Extract entries for this category using tr to split on semicolons
    items=$(echo "$ALL_ENTRIES" | tr ';' '\n' | grep "^${cat_type}::")
    if [[ -n "$items" ]]; then
        count=$(echo "$items" | wc -l | tr -d ' ')
        label="${CATEGORY_LABELS[$cat_type]:-Other}"
        echo "## ${label} (${count})"
        echo "$items" | while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            # Strip the "type::" prefix
            entry="${item#*::}"
            echo "$entry"
        done
        echo ""
    fi
done

# Contributors section
echo "## Contributors"
echo ""

# Extract authors from original log data step by step
authors=$(echo "$GIT_LOG" | awk -F'|' '{print $2}')
sorted_authors=$(echo "$authors" | sort)
author_counts=$(echo "$sorted_authors" | uniq -c)

echo "$author_counts" | while read count author; do
    [[ -z "$author" ]] && continue
    echo "- ${author}: ${count} commit(s)"
done

# Count unique contributors
NUM_AUTHORS=$(echo "$sorted_authors" | uniq | wc -l | tr -d ' ')

echo ""
echo "---"
echo "*${TOTAL_COMMITS} commits by ${NUM_AUTHORS} contributors*"
