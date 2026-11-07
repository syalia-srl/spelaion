#!/bin/bash
# Real-world problem: Given a set of packages with dependencies, compute
# the correct build order using topological sort. Build systems and package
# managers need this to avoid compiling things before their deps are ready.
#
# Bash features exercised:
#   associative arrays, indexed arrays, while loops, nested for loops,
#   string splitting with IFS, [[ -z ]], arithmetic, here-document,
#   parameter expansion, function definitions with local vars

# Dependency declarations: "package: dep1 dep2 dep3"
DEPS_SPEC=$(cat <<'DEPEOF'
libssl:
libcurl: libssl
libz:
libxml: libz
app-core: libcurl libxml
app-api: app-core
app-cli: app-core
app-web: app-api libcurl
test-suite: app-cli app-api app-web
DEPEOF
)

declare -A DEPS       # package -> space-separated deps
declare -A IN_DEGREE  # package -> number of unresolved deps
declare -a ALL_PKGS   # all package names
declare -a BUILD_ORDER

# Parse dependency spec
while IFS=':' read -r pkg deplist; do
    pkg="${pkg## }"
    pkg="${pkg%% }"
    deplist="${deplist## }"
    deplist="${deplist%% }"

    ALL_PKGS+=("$pkg")
    DEPS[$pkg]="$deplist"
    IN_DEGREE[$pkg]=0
done <<< "$DEPS_SPEC"

# Calculate in-degrees
for pkg in "${ALL_PKGS[@]}"; do
    for dep in ${DEPS[$pkg]}; do
        if [[ -n "$dep" ]]; then
            current="${IN_DEGREE[$pkg]}"
            IN_DEGREE[$pkg]=$((current + 1))
        fi
    done
done

echo "=== Dependency Graph ==="
for pkg in "${ALL_PKGS[@]}"; do
    deps="${DEPS[$pkg]}"
    if [[ -z "$deps" ]]; then
        deps="(none)"
    fi
    printf "  %-15s -> %s\n" "$pkg" "$deps"
done
echo ""

# Topological sort (Kahn's algorithm)
declare -a QUEUE

# Seed queue with zero in-degree nodes
for pkg in "${ALL_PKGS[@]}"; do
    if [[ "${IN_DEGREE[$pkg]}" -eq 0 ]]; then
        QUEUE+=("$pkg")
    fi
done

STEP=0
echo "=== Build Order ==="
while [[ ${#QUEUE[@]} -gt 0 ]]; do
    # Dequeue first element
    CURRENT="${QUEUE[0]}"
    QUEUE=("${QUEUE[@]:1}")

    STEP=$((STEP + 1))
    BUILD_ORDER+=("$CURRENT")
    echo "  ${STEP}. ${CURRENT}"

    # Reduce in-degree of dependents
    for pkg in "${ALL_PKGS[@]}"; do
        for dep in ${DEPS[$pkg]}; do
            if [[ "$dep" == "$CURRENT" ]]; then
                IN_DEGREE[$pkg]=$((${IN_DEGREE[$pkg]} - 1))
                if [[ ${IN_DEGREE[$pkg]} -eq 0 ]]; then
                    QUEUE+=("$pkg")
                fi
            fi
        done
    done
done

echo ""

# Cycle detection
if [[ ${#BUILD_ORDER[@]} -ne ${#ALL_PKGS[@]} ]]; then
    echo "ERROR: Circular dependency detected!"
    echo "  Built ${#BUILD_ORDER[@]} of ${#ALL_PKGS[@]} packages"
else
    echo "=== Summary ==="
    echo "  All ${#ALL_PKGS[@]} packages can be built in ${STEP} steps"
    echo "  Order: ${BUILD_ORDER[*]}"
fi
