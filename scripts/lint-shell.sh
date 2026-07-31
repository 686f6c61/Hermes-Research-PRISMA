#!/usr/bin/env bash
set -euo pipefail

# Git can still list tracked files that are deleted in the current release.
# Build the argument list explicitly so ShellCheck only receives real files.
shell_files=()
while IFS= read -r -d '' path; do
  if [[ -f "${path}" ]]; then
    shell_files+=("${path}")
  fi
done < <(git ls-files -z '*.sh')

if (( ${#shell_files[@]} == 0 )); then
  printf 'No shell scripts found.\n'
  exit 0
fi

shellcheck "${shell_files[@]}"
