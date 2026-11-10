# The shell functions of a scope-lineage run. Sourced by the last line of $RUN/env.sh
# (written by scripts/init_run.py); every Bash call of a run starts with `. "$RUN/env.sh"`.
# Works under bash and zsh. Reads TOOL, SKILL, RUN from the environment env.sh set.

: "${SKILL:=${TOOL:+$TOOL/skills/scope-lineage}}"
export SKILL

# The tool: a checkout when TOOL is set, the installed package when it is empty.
sl() { if [ -n "$TOOL" ]; then uv run --project "$TOOL" --extra catalog scope-lineage "$@"; else scope-lineage "$@"; fi; }

# The tool's JSON Schemas: in the checkout, or found in the installed package.
export SCHEMAS="${SCHEMAS:-${TOOL:+$TOOL/scope_lineage/schemas}}"
[ -n "$SCHEMAS" ] || SCHEMAS="$(python3 -c 'import importlib.util as u, os; print(os.path.join(u.find_spec("scope_lineage").submodule_search_locations[0], "schemas"))' 2>/dev/null)"

# tables.txt into the array TABLES; fails when it holds no table.
load_tables() {
  TABLES=(); while IFS= read -r t; do [ -n "$t" ] && TABLES+=("$t"); done < "$RUN/tables.txt"
  echo "tables=${#TABLES[@]}"; [ "${#TABLES[@]}" -gt 0 ]
}

# One line in the ledger: the last command of every step, e.g. note "S4 派 T1 demo_dwd.x 第1轮"
note() {
  printf -- '- %s %s\n' "$(date '+%F %T')" "$*" >> "$RUN/ledger.md"
}

# Fill a subagent prompt template: fill <template> <output file> KEY=value ...
fill() { python3 "$SKILL/scripts/fill.py" "$@"; }

set -o pipefail
