#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
revision=3de37c8cfb039452be7398909461da6288babf15
if [[ -e Telegram ]]; then
  echo 'Telegram already exists. Use a new directory to avoid modifying an existing checkout.' >&2
  exit 1
fi
git init Telegram
git -C Telegram remote add origin https://github.com/DrKLO/Telegram.git
git -C Telegram fetch --depth 1 origin "$revision"
git -C Telegram checkout --detach FETCH_HEAD
git -C Telegram submodule update --init --recursive --depth 1 --jobs 4
python3 apply.py Telegram
