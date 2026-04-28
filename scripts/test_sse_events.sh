#!/usr/bin/env bash
# Test driver for the matter SSE notification stream.
#
# Reads BASE + SID from the environment, then drives the event types
# end-to-end:
#   1. POST /api/matters                  -> matter.created (+ file_appended)
#   2. POST /api/matters/{id}/files       -> matter.updated reason=file_appended
#   3. burst 5x append                    -> 5 file_appended frames (debounce check)
#   4. POST /api/matters/{id}/comments    -> comment_appended with @mentions
#                                            (verifies Feishu DM notify path)
#
# Inter-step values (matter_id / target_file) are extracted from the previous
# response automatically, so you only need to set BASE + SID once. Pair this
# script with a separate terminal listening:
#   curl -N --cookie "sid=$SID" "$BASE/api/matters/events"
#
# Usage:
#   export BASE=http://localhost:8000
#   export SID=<your-session-id>
#   ./scripts/test_sse_events.sh             # run all steps
#   ./scripts/test_sse_events.sh create      # run a single step
#                                            #   (create|append|burst|mention)
#   ./scripts/test_sse_events.sh listen      # tail the SSE stream in this terminal

set -euo pipefail

require_env() {
  : "${BASE:?BASE env var is required, e.g. http://localhost:8000}"
  : "${SID:?SID env var is required (copy from browser DevTools cookies)}"
}

# Unique matter id per run so re-runs don't collide on slug. ASCII only to
# guarantee FastAPI/curl/shell encoding stays out of the way.
RUN_ID="sse-$(date +%s)"

# On Git Bash / MSYS, mktemp returns a POSIX path like /tmp/foo, but a native
# Windows curl.exe doesn't honor MSYS path translation and writes to literal
# C:\tmp\foo (where bash later can't find it). Translate to a Windows path via
# cygpath when available so both sides see the same location.
TMP="$(mktemp -d -t sse-test.XXXXXX)"
if command -v cygpath >/dev/null 2>&1; then
  TMP="$(cygpath -w "$TMP")"
fi
trap 'rm -rf "$TMP"' EXIT

cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }

# Tiny JSON-field extractor that doesn't depend on jq. Path is dot-separated;
# numeric segments are treated as list indices. Pass file + path as argv so
# Windows backslash paths don't need shell-quoting tricks.
json_get() {
  local file="$1" path="$2"
  python -c '
import json,sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
for key in sys.argv[2].split("."):
    if key.lstrip("-").isdigit():
        data = data[int(key)]
    else:
        data = data[key]
print(data)
' "$file" "$path"
}

post_json() {
  # post_json <path> <body-file>  -> writes response to $TMP/last.json,
  # exits non-zero with body printed if HTTP status is not 2xx.
  local route="$1" body_file="$2"
  local status
  status=$(
    curl -sS -o "$TMP/last.json" -w '%{http_code}' \
      -X POST "$BASE$route" \
      -H 'Content-Type: application/json; charset=utf-8' \
      --cookie "sid=$SID" \
      --data-binary "@$body_file"
  )
  if [[ ! "$status" =~ ^2 ]]; then
    red "POST $route -> HTTP $status"
    cat "$TMP/last.json" >&2
    echo >&2
    return 1
  fi
}

step_create() {
  cyan "[1/4] POST /api/matters  (matter_id=$RUN_ID)"
  cat > "$TMP/new.json" <<EOF
{"category":"test","title":"$RUN_ID","initial_file":{"type":"think","summary":"sse smoke - create","body":"x"}}
EOF
  post_json "/api/matters" "$TMP/new.json"
  local mid
  mid=$(json_get "$TMP/last.json" matter_id)
  if [[ "$mid" != "$RUN_ID" ]]; then
    red "matter_id mismatch: expected $RUN_ID, got $mid"
    return 1
  fi
  green "    -> matter_id=$mid (expect: matter.created + file_appended on the SSE stream)"
}

step_append() {
  cyan "[2/4] POST /api/matters/$RUN_ID/files"
  cat > "$TMP/append.json" <<'EOF'
{"type":"think","summary":"sse smoke - append","body":"reply body"}
EOF
  post_json "/api/matters/$RUN_ID/files" "$TMP/append.json"
  local file
  file=$(json_get "$TMP/last.json" item.file)
  echo "$file" > "$TMP/last_file.txt"
  green "    -> file=$file (expect: matter.updated reason=file_appended)"
}

step_burst() {
  cyan "[3/4] burst 5x POST /api/matters/$RUN_ID/files (debounce check)"
  for i in 1 2 3 4 5; do
    cat > "$TMP/burst.json" <<EOF
{"type":"think","summary":"burst $i","body":"$i"}
EOF
    post_json "/api/matters/$RUN_ID/files" "$TMP/burst.json"
  done
  green "    -> 5 frames sent; front-end should refetch /api/matters ONCE (300ms debounce)"
}

# @-mention test. Issues a comment with the `mentions` array populated and
# verifies the SSE comment_appended frame still fires. Receivers (users in
# MENTION_OPEN_IDS) should also get a Feishu DM if notifier is enabled
# server-side; that path is independent of the SSE stream.
MENTION_OPEN_IDS=(
  "ou_8868d9577259734d8a462aaec8b9140d"
  "tank2"
)

step_mention() {
  # Give the previous bursts time to drain through the SSE pipeline + the
  # front-end debounce window before we fire the mention. Makes the @-mention
  # frame easy to spot in the listener and the Feishu DM easy to attribute.
  cyan "[4/4] sleeping 10s before mention test..."
  sleep 300
  cyan "[4/4] POST /api/matters/$RUN_ID/comments  (with @mentions)"
  local target
  if [[ -f "$TMP/last_file.txt" ]]; then
    target=$(cat "$TMP/last_file.txt")
  else
    curl -sS --cookie "sid=$SID" "$BASE/api/matters/$RUN_ID" > "$TMP/detail.json"
    target=$(json_get "$TMP/detail.json" timeline.-1.file 2>/dev/null || true)
    if [[ -z "$target" ]]; then
      red "no timeline entries to mention on; run 'create' or 'append' first"
      return 1
    fi
  fi
  python -c '
import json,sys
target = sys.argv[1]
out = sys.argv[2]
mentions = sys.argv[3:]
body = {
    "target_file": target,
    "body": "sse smoke - mention " + " ".join("@" + m for m in mentions),
    "mentions": mentions,
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(body, f, ensure_ascii=False)
' "$target" "$TMP/mention.json" "${MENTION_OPEN_IDS[@]}"
  post_json "/api/matters/$RUN_ID/comments" "$TMP/mention.json"
  green "    -> mentioned ${MENTION_OPEN_IDS[*]} on $target"
  green "       (expect: matter.updated reason=comment_appended on the SSE stream;"
  green "        and a Feishu DM to each mentioned user if notifier is enabled)"
}

step_listen() {
  cyan "tailing $BASE/api/matters/events  (Ctrl+C to stop)"
  exec curl -N --cookie "sid=$SID" "$BASE/api/matters/events"
}

main() {
  local cmd="${1:-all}"
  case "$cmd" in
    -h|--help|help)
      sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//' | head -n -2
      return 0
      ;;
  esac
  require_env
  case "$cmd" in
    create)  step_create ;;
    append)  step_create; step_append ;;
    burst)   step_create; step_burst ;;
    mention) step_create; step_append; step_mention ;;
    listen)  step_listen ;;
    all)     step_create; step_append; step_burst; step_mention
             green "all done. matter_id=$RUN_ID" ;;
    *)
      red "unknown command: $cmd (use one of: create | append | burst | mention | listen | all)"
      exit 2
      ;;
  esac
}

main "$@"
