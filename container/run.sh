#!/bin/sh

dir="$(realpath -m "$0/../..")"
cimg="${dir}/cimg"

"${cimg}" update
"${cimg}" server
