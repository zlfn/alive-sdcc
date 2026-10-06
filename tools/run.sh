#!/bin/sh
# Proves the rules that convert.py wrote, one rule at a time and JOBS at
# once, and writes what z80-test says next to each file. Z80_TEST names the
# z80-test to run. A rule that has a copy without the flags stops at its
# first counterexample: the copy shows the rest.
out=${1:-$(dirname "$0")/../rules}
tmp=$(mktemp -d)
trap 'rm -r "$tmp"' EXIT
for f in "$out"/z80.rules "$out"/z80-noflags.rules "$out"/sm83.rules \
         "$out"/sm83-noflags.rules; do
    grep '^rule ' "$f" | cut -d' ' -f2 | sed "s|^|$f |"
done | xargs -P "${JOBS:-$(nproc)}" -L1 sh -c '
    f=$1 rule=$2
    cpu=$(basename "$f" .rules | cut -d- -f1)
    stop=0
    if grep -qx "rule $rule" "${f%.rules}-noflags.rules" 2>/dev/null; then
        stop=1
    fi
    mkdir -p "'"$tmp"'/$(basename "$f")"
    "${Z80_TEST:-z80-test}" --cpu="$cpu" --smt-timeout=60 --reports=20 \
        --max-failures=$stop "$f" "$rule" \
        > "'"$tmp"'/$(basename "$f")/$rule" 2>&1' sh
for f in "$out"/z80.rules "$out"/z80-noflags.rules "$out"/sm83.rules \
         "$out"/sm83-noflags.rules; do
    grep '^rule ' "$f" | cut -d' ' -f2 |
        while read -r rule; do cat "$tmp/$(basename "$f")/$rule"; done \
        > "${f%.rules}.txt"
    echo "$(basename "$f"): $(grep -cE '^\S+ +ok ' "${f%.rules}.txt") ok," \
        "$(grep -cE '^\S+ +FAIL' "${f%.rules}.txt") failed"
done
