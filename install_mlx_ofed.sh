#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

ENABLE_MLX=${ENABLE_MLX:-0}
MLX_OFED_VERSION="5.4-3.1.0.0"

SUDO=''
[[ $EUID -ne 0 ]] && SUDO=sudo

install_mlx() {
	mkdir /tmp/mlx
	pushd /tmp/mlx
	curl -L https://content.mellanox.com/ofed/MLNX_OFED-${MLX_OFED_VERSION}/MLNX_OFED_LINUX-${MLX_OFED_VERSION}-ubuntu20.04-x86_64.tgz | \
    		tar xz -C . --strip-components=2
	./mlnxofedinstall --with-mft --with-mstflint --auto-add-kernel-support --without-fw-update --dpdk --upstream-libs --force
	popd
}

cleanup_image() {
	$SUDO rm -rf /tmp/mlx
}

(return 2>/dev/null) && echo "Sourced" && return

set -o errexit
set -o pipefail
set -o nounset

[ "$ENABLE_MLX" == "0" ] && exit 0

echo "Installing MLX OFED driver..."
install_mlx

echo "Cleaning up..."
cleanup_image
