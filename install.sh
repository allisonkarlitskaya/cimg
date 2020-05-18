#!/bin/sh -ex

srcdir="$(realpath -m "$0/..")"
mkdir -p ~/.local/bin
ln -Tsf "${srcdir}/cimg" ~/.local/bin/cimg
mkdir -p ~/.local/share/bash-completion/completions
ln -Tsf "${srcdir}/cimg.bash-completion" ~/.local/share/bash-completion/completions/cimg
