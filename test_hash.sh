#!/bin/zsh
typeset -A PIDS
sleep 100 &
PIDS[backend]=$!
echo "Backend pid: ${PIDS[backend]}"
kill -0 "${PIDS[backend]}" && echo alive || echo dead
kill "${PIDS[backend]}"

