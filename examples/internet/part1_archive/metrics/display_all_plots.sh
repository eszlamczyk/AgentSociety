#!/bin/bash

DESIRED_DIRECTORY="$1"

cd "$(dirname "$0")/$DESIRED_DIRECTORY" || exit 1

for file in *.png; do
    mupdf "$file"
done
