#!/bin/bash
# Real-world problem: Bootstrap a development machine by detecting the OS,
# checking prerequisites, and reporting what needs to be installed. Used by
# teams to onboard new developers consistently.
#
# Bash features exercised:
#   case statement with compound patterns (|), functions with return codes,
#   [[ -z ]], [[ -n ]], command substitution, arrays, string comparison,
#   parameter expansion ${var:-default}, here-document, arithmetic

# Simulated environment (normally detected from actual system)
SIMULATED_OS="${TEST_OS:-linux}"
SIMULATED_DISTRO="${TEST_DISTRO:-ubuntu}"
SIMULATED_ARCH="${TEST_ARCH:-x86_64}"

# Required tools and their minimum versions
declare -A REQUIRED_TOOLS
REQUIRED_TOOLS[python]="3.11"
REQUIRED_TOOLS[node]="18.0"
REQUIRED_TOOLS[docker]="24.0"
REQUIRED_TOOLS[git]="2.40"
REQUIRED_TOOLS[make]="4.0"

# Simulated installed versions (normally: tool --version | parse)
declare -A INSTALLED_TOOLS
INSTALLED_TOOLS[python]="3.12.1"
INSTALLED_TOOLS[node]=""
INSTALLED_TOOLS[docker]="24.0.7"
INSTALLED_TOOLS[git]="2.43.0"
INSTALLED_TOOLS[make]="4.3"

detect_os() {
    local os="$SIMULATED_OS"
    local distro="$SIMULATED_DISTRO"

    case "$os" in
        linux)
            case "$distro" in
                ubuntu|debian)
                    PKG_MANAGER="apt"
                    PKG_INSTALL="apt-get install -y"
                    ;;
                fedora|rhel|centos)
                    PKG_MANAGER="dnf"
                    PKG_INSTALL="dnf install -y"
                    ;;
                arch)
                    PKG_MANAGER="pacman"
                    PKG_INSTALL="pacman -S --noconfirm"
                    ;;
                *)
                    PKG_MANAGER="unknown"
                    PKG_INSTALL="echo INSTALL:"
                    ;;
            esac
            ;;
        darwin)
            PKG_MANAGER="brew"
            PKG_INSTALL="brew install"
            ;;
        *)
            echo "ERROR: Unsupported OS: ${os}" >&2
            return 1
            ;;
    esac

    echo "Detected: ${os}/${distro} (${SIMULATED_ARCH})"
    echo "Package manager: ${PKG_MANAGER}"
    return 0
}

version_gte() {
    local installed="$1"
    local required="$2"

    # Compare major.minor
    local inst_major="${installed%%.*}"
    local inst_rest="${installed#*.}"
    local inst_minor="${inst_rest%%.*}"

    local req_major="${required%%.*}"
    local req_rest="${required#*.}"
    local req_minor="${req_rest%%.*}"

    if [[ $inst_major -gt $req_major ]]; then
        return 0
    elif [[ $inst_major -eq $req_major ]] && [[ $inst_minor -ge $req_minor ]]; then
        return 0
    fi
    return 1
}

echo "=== Development Environment Bootstrap ==="
echo ""

detect_os
if [[ $? -ne 0 ]]; then
    exit 1
fi

echo ""
echo "--- Checking Prerequisites ---"

MISSING=0
OUTDATED=0
OK_COUNT=0
declare -a INSTALL_COMMANDS

for tool in $(echo "${!REQUIRED_TOOLS[@]}" | tr ' ' '\n' | sort); do
    required="${REQUIRED_TOOLS[$tool]}"
    installed="${INSTALLED_TOOLS[$tool]}"

    if [[ -z "$installed" ]]; then
        printf "  %-12s %-15s %s\n" "$tool" "[MISSING]" "need >=${required}"
        INSTALL_COMMANDS+=("${PKG_INSTALL} ${tool}")
        MISSING=$((MISSING + 1))
    elif version_gte "$installed" "$required"; then
        printf "  %-12s %-15s %s\n" "$tool" "[OK ${installed}]" ">=${required}"
        OK_COUNT=$((OK_COUNT + 1))
    else
        printf "  %-12s %-15s %s\n" "$tool" "[OLD ${installed}]" "need >=${required}"
        INSTALL_COMMANDS+=("${PKG_INSTALL} ${tool}")
        OUTDATED=$((OUTDATED + 1))
    fi
done

TOTAL_TOOLS=${#REQUIRED_TOOLS[@]}
echo ""
echo "--- Summary ---"
echo "  OK: ${OK_COUNT}/${TOTAL_TOOLS}"
echo "  Missing: ${MISSING}"
echo "  Outdated: ${OUTDATED}"

if [[ ${#INSTALL_COMMANDS[@]} -gt 0 ]]; then
    echo ""
    echo "--- Install Commands ---"
    for cmd in "${INSTALL_COMMANDS[@]}"; do
        echo "  $ ${cmd}"
    done
fi
