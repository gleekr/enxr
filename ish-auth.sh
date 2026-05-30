#!/bin/sh
set -e

printf "GitHub token: "
stty -echo 2>/dev/null; read TOKEN; stty echo 2>/dev/null
printf "\n"

[ -z "$TOKEN" ] && printf "no token\n" && exit 1

git config --global user.name gleekr
git config --global user.email gleeky@tuta.io
git config --global github.token "$TOKEN"
git config --global credential.helper store

printf "machine github.com\nlogin gleekr\npassword %s\n" "$TOKEN" > ~/.netrc
chmod 600 ~/.netrc

printf "[ok] auth done\n"
