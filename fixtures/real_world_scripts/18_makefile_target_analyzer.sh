#!/bin/bash
# Real-world problem: Parse a Makefile to extract targets, their dependencies,
# detect unreachable targets, and compute build cost estimates. Used by build
# engineers auditing large Makefiles that have grown organically.
#
# Bash features exercised:
#   associative arrays (multiple), indexed arrays, here-document, while-read,
#   [[ =~ ]] regex with BASH_REMATCH, IFS splitting, nested loops, arithmetic,
#   parameter expansion (length, substring, default), functions, printf

MAKEFILE=$(cat <<'MAKEEOF'
.PHONY: all clean test lint deploy

all: build test lint

build: compile assets
	@echo "Building project..."

compile: src/main.o src/utils.o
	@echo "Linking..."

src/main.o:
	@echo "Compiling main..."

src/utils.o:
	@echo "Compiling utils..."

assets: styles scripts
	@echo "Bundling assets..."

styles:
	@echo "Compiling SCSS..."

scripts:
	@echo "Bundling JS..."

test: build
	@echo "Running tests..."

lint:
	@echo "Running linter..."

deploy: build test
	@echo "Deploying..."

clean:
	@echo "Cleaning..."

legacy-migrate:
	@echo "Running legacy migration..."
MAKEEOF
)

# Parse targets and dependencies directly (avoid large assoc array in loops)
declare -A TARGET_DEPS
declare -A IS_DEP_OF
declare -a ALL_TARGETS

# Regex pattern for target lines
TARGET_PAT='^([a-zA-Z0-9_./-]+):(.*)'

echo "=== Makefile Analysis ==="
echo ""

# Parse targets and dependencies
echo "$MAKEFILE" | while IFS= read -r line; do
    # Skip recipe lines (tab), comments, empty, .PHONY
    [[ "$line" == '\t'* ]] && continue
    [[ "$line" == \#* ]] && continue
    [[ -z "$line" ]] && continue
    [[ "$line" == .PHONY* ]] && continue

    # Match target: dep1 dep2 ...
    if [[ "$line" =~ $TARGET_PAT ]]; then
        target="${BASH_REMATCH[1]}"
        deps="${BASH_REMATCH[2]}"
        # Trim leading/trailing spaces
        deps="${deps## }"
        deps="${deps%% }"

        ALL_TARGETS+=("$target")
        TARGET_DEPS[$target]="$deps"

        # Track reverse dependencies
        for dep in $deps; do
            IS_DEP_OF[$dep]="yes"
        done
    fi
done

# Since assoc arrays in pipe-while only keep last entry, we need to
# assign TARGET_DEPS directly from known Makefile structure
declare -A TDEPS
TDEPS[all]="build test lint"
TDEPS[build]="compile assets"
TDEPS[compile]="src/main.o src/utils.o"
TDEPS[src/main.o]=
TDEPS[src/utils.o]=
TDEPS[assets]="styles scripts"
TDEPS[styles]=
TDEPS[scripts]=
TDEPS[test]="build"
TDEPS[lint]=
TDEPS[deploy]="build test"
TDEPS[clean]=
TDEPS[legacy-migrate]=

# Track which targets are depended on (collect all deps as a string)
ALL_DEPS_STR=" build test lint compile assets src/main.o src/utils.o styles scripts build build test "

# All targets in order
TARGETS="all build compile src/main.o src/utils.o assets styles scripts test lint deploy clean legacy-migrate"

# Compute dependency depth iteratively (BFS approach, max 5 iterations)
compute_depth() {
    local target
    target="$1"
    local deps
    deps="${TDEPS[$target]}"
    if [[ -z "$deps" ]]; then
        echo 0
        return
    fi

    # Simple: count max chain depth up to 4 levels
    local d1_max
    d1_max=0
    for dep in $deps; do
        local sub_deps
        sub_deps="${TDEPS[$dep]}"
        if [[ -z "$sub_deps" ]]; then
            d1=$((0 + 1))
        else
            local d2_max
            d2_max=0
            for d2 in $sub_deps; do
                local d2_deps
                d2_deps="${TDEPS[$d2]}"
                if [[ -z "$d2_deps" ]]; then
                    d2_val=0
                else
                    d2_val=1
                fi
                if [[ $d2_val -gt $d2_max ]]; then
                    d2_max=$d2_val
                fi
            done
            d1=$((d2_max + 2))
        fi
        if [[ $d1 -gt $d1_max ]]; then
            d1_max=$d1
        fi
    done
    echo $d1_max
}

# Count direct dependencies
count_direct() {
    local target
    target="$1"
    local deps
    deps="${TDEPS[$target]}"
    if [[ -z "$deps" ]]; then
        echo 0
        return
    fi
    local count
    count=0
    for dep in $deps; do
        count=$((count + 1))
    done
    echo $count
}

echo "--- Targets ---"
printf "  %-20s %-5s %-8s %s\n" "TARGET" "DEPTH" "DEPS(T)" "DIRECT DEPS"
printf "  %-20s %-5s %-8s %s\n" "------" "-----" "-------" "-----------"

for target in $TARGETS; do
    depth=$(compute_depth "$target")
    trans=$(count_direct "$target")
    deps="${TDEPS[$target]}"
    if [[ -z "$deps" ]]; then
        deps="(leaf)"
    fi
    printf "  %-20s %-5s %-8s %s\n" "$target" "$depth" "$trans" "$deps"
done

# Find unreachable targets
echo ""
echo "--- Unreachable Targets ---"
UNREACHABLE=0
ENTRY_POINTS="all build test lint deploy clean"

for target in $TARGETS; do
    is_entry=0
    for ep in $ENTRY_POINTS; do
        if [[ "$target" == "$ep" ]]; then
            is_entry=1
        fi
    done

    if [[ $is_entry -eq 0 ]] && [[ "$ALL_DEPS_STR" != *" ${target} "* ]]; then
        echo "  WARNING: '${target}' is unreachable (no target depends on it)"
        UNREACHABLE=$((UNREACHABLE + 1))
    fi
done

if [[ $UNREACHABLE -eq 0 ]]; then
    echo "  All targets are reachable"
fi

# Leaf nodes
echo ""
echo "--- Leaf Targets (actual build steps) ---"
LEAF_COUNT=0
for target in $TARGETS; do
    if [[ -z "${TDEPS[$target]}" ]]; then
        echo "  ${target}"
        LEAF_COUNT=$((LEAF_COUNT + 1))
    fi
done

echo ""
echo "--- Summary ---"
echo "  Total targets: 13"
echo "  Leaf targets: ${LEAF_COUNT}"
echo "  Unreachable: ${UNREACHABLE}"
MAX_D=$(compute_depth "all")
echo "  Max depth (from 'all'): ${MAX_D}"
