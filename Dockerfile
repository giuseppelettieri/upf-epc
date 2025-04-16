# SPDX-License-Identifier: Apache-2.0
# Copyright 2020-present Open Networking Foundation
# Copyright 2019-present Intel Corporation

# Stage bess-build: fetch BESS dependencies & pre-reqs
FROM registry.aetherproject.org/sdcore/bess_build:latest AS bess-build
ARG CPU=native
ENV PLUGINS_DIR=plugins
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install \
        ca-certificates python3-pip software-properties-common \
        libelf-dev sudo kmod python3-pyverbs curl python-is-python3 \
        linux-tools-common linux-tools-generic \
        python3-pyverbs pkg-config git make apt-transport-https \
        g++ libunwind8-dev liblzma-dev zlib1g-dev \
        libpcap-dev libssl-dev libnuma-dev git \
        python3-scapy libgflags-dev libgoogle-glog-dev \
        libgraph-easy-perl libgtest-dev \
        libc-ares-dev libbenchmark-dev \
        libgtest-dev wget autoconf \
        automake cmake libtool \
        make ninja-build patch python3-pip \
        unzip virtualenv zip tar meson \
        libelf-dev libz-dev libnl-3-dev

ARG MAKEFLAGS
ENV PKG_CONFIG_PATH=/usr/lib64/pkgconfig

## Mellanox OFED Driver
ARG ENABLE_MLX
COPY install_mlx_ofed.sh .
RUN ./install_mlx_ofed.sh

WORKDIR /grpc
ARG GRPC_VER=v1.44.0
RUN git clone https://github.com/grpc/grpc --branch ${GRPC_VER} --single-branch && \
    cd /grpc/grpc && git submodule init && git submodule update --recursive
RUN cd /grpc/grpc && mkdir -p cmake/build && cd cmake/build && \
    cmake ../.. -DgRPC_INSTALL=ON              \
              -DCMAKE_BUILD_TYPE=Release       \
              -DgRPC_ABSL_PROVIDER=module     \
              -DgRPC_CARES_PROVIDER=module    \
              -DgRPC_PROTOBUF_PROVIDER=module \
              -DgRPC_RE2_PROVIDER=module      \
              -DgRPC_SSL_PROVIDER=package      \
              -DgRPC_ZLIB_PROVIDER=package &&  \
    make -j$(getconf _NPROCESSORS_ONLN) && sudo make install

RUN cd /grpc/grpc/third_party/protobuf && \
    git submodule update --init --recursive && \
    ./autogen.sh && ./configure && \
    make -j$(getconf _NPROCESSORS_ONLN) && sudo make install && sudo ldconfig

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install \
        curl zip unzip tar meson

# The following packages are needed to run bessctl
RUN pip3 install --user protobuf grpcio scapy

# linux ver should match target machine's kernel
WORKDIR /libbpf
ARG LIBBPF_VER=v1.5.0
RUN git clone https://github.com/libbpf/libbpf.git --branch ${LIBBPF_VER} --single-branch && \
    cd libbpf/src && make install && make install_uapi_headers && \
    ldconfig

WORKDIR /bpftool
COPY xdp-plugin xdp-scripts
RUN ./xdp-scripts/install-dependencies.sh && \
    rm -rf /bpftool

RUN wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key|sudo apt-key add - && \
    add-apt-repository -y "deb http://apt.llvm.org/focal/ llvm-toolchain-focal-18 main" && \
    apt-get update && apt-get install -y clang-18 clang-tools-18 clang-format-18 llvm-18 llvm-18-dev llvm-18-tools llvm-18-runtime && \
    update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 100 \
    --slave /usr/bin/clang++ clang++ /usr/bin/clang++-18 \
    --slave /usr/bin/llc llc /usr/bin/llc-18 && \
    update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-18 100

WORKDIR /libxdp
ARG LIBXDP_VER=libxdp-cpp-v1.5.0
RUN git clone https://github.com/alefais/xdp-tools.git --branch ${LIBXDP_VER} --single-branch && \
    cd xdp-tools && ./configure && make libxdp && \
    sudo make libxdp install

RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    git \
    ca-certificates \
    libbpf0 \
    libelf-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# BESS pre-reqs
WORKDIR /bess
ARG BESS_COMMIT=seb
RUN git clone https://github.com/giuseppelettieri/bess.git . && \
    git checkout ${BESS_COMMIT} && \
    cp -a protobuf /protobuf

# Build DPDK
RUN ./build.py dpdk

# Plugins: SequentialUpdate
RUN mkdir -p plugins && \
    mv sample_plugin plugins

COPY upf-ebpf upf-ebpf
COPY upf-ebpf/protobuf/upf_ebpf_msg.proto /protobuf/
RUN mv upf-ebpf plugins/upf-ebpf

## Network Token
ARG ENABLE_NTF
ARG NTF_COMMIT=master
COPY scripts/install_ntf.sh .
RUN ./install_ntf.sh

# Build and copy artifacts
RUN PLUGINS=$(find "$PLUGINS_DIR" -mindepth 1 -maxdepth 1 -type d) && \
    CMD="./build.py bess" && \
    for PLUGIN in $PLUGINS; do \
        CMD="$CMD --plugin \"$PLUGIN\""; \
    done && \
    eval "$CMD" && \
    cp bin/bessd /bin && \
    mkdir -p /bin/modules && \
    cp core/modules/*.so /bin/modules && \
    mkdir -p /opt/bess && \
    cp -r bessctl pybess /opt/bess && \
    cp -r core/pb /pb 

# Stage bess: creates the runtime image of BESS
FROM ubuntu:24.04 AS bess
WORKDIR /
COPY requirements.txt .
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    python3-pip \
    libgraph-easy-perl \
    iproute2 \
    iptables \
    iputils-ping \
    tcpdump && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --break-system-packages -r requirements.txt

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install \
        ca-certificates python3-pip software-properties-common \
        libelf-dev sudo kmod python3-pyverbs curl python-is-python3 \
        linux-tools-common linux-tools-generic \
        python3-pyverbs pkg-config git make apt-transport-https \
        g++ libunwind8-dev liblzma-dev zlib1g-dev \
        libpcap-dev libssl-dev libnuma-dev git \
        python3-scapy libgflags-dev libgoogle-glog-dev \
        libgraph-easy-perl libgtest-dev \
        libc-ares-dev libbenchmark-dev \
        libgtest-dev wget autoconf \
        automake cmake libtool \
        make ninja-build patch python3-pip \
        unzip virtualenv zip tar meson \
        libelf-dev libz-dev libnl-3-dev clang llvm

## Mellanox OFED Driver
ARG ENABLE_MLX
COPY install_mlx_ofed.sh .
RUN ./install_mlx_ofed.sh

# linux ver should match target machine's kernel
WORKDIR /libbpf
ARG LIBBPF_VER=v1.5.0
RUN git clone https://github.com/libbpf/libbpf.git --branch ${LIBBPF_VER} --single-branch && \
    cd libbpf/src && make install && make install_uapi_headers && \
    ldconfig

WORKDIR /bpftool
COPY xdp-plugin xdp-scripts
RUN ./xdp-scripts/install-dependencies.sh && \
    rm -rf /bpftool

# RUN update-alternatives --install /usr/bin/clang++ clang++ /usr/bin/clang++-12 100 && \
#     update-alternatives --install /usr/bin/clang clang /usr/bin/clang-12 100

WORKDIR /libxdp
ARG LIBXDP_VER=libxdp-cpp-v1.5.0
RUN git clone https://github.com/alefais/xdp-tools.git --branch ${LIBXDP_VER} --single-branch && \
    cd xdp-tools && ./configure && make libxdp && \
    sudo make libxdp install && sudo ldconfig

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get --purge remove -y \
        gcc

COPY --from=bess-build /opt/bess /opt/bess
COPY --from=bess-build /bin/bessd /bin/bessd
COPY --from=bess-build /bin/modules /bin/modules
COPY conf /opt/bess/bessctl/conf
COPY upf-ebpf/bessctl_conf/upf-ebpf.bess /opt/bess/bessctl/conf/upf-ebpf.bess
COPY upf-ebpf/bessctl_conf/upf-ebpf-af_xdp.bess /opt/bess/bessctl/conf/upf-ebpf-af_xdp.bess
RUN ln -s /opt/bess/bessctl/bessctl /bin

# CNDP: Install dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    build-essential \
    ethtool \
    libbsd0 \
    libelf1 \
    libgflags2.2 \
    libjson-c[45] \
    libnl-3-200 \
    libnl-cli-3-200 \
    libnuma1 \
    libpcap0.8 \
    pkg-config && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
COPY --from=bess-build /usr/bin/cndpfwd /usr/bin/
COPY --from=bess-build /usr/local/lib/x86_64-linux-gnu/*.so /usr/local/lib/x86_64-linux-gnu/
COPY --from=bess-build /usr/local/lib/x86_64-linux-gnu/*.a /usr/local/lib/x86_64-linux-gnu/
COPY --from=bess-build /usr/lib/libxdp* /usr/lib/
COPY --from=bess-build /usr/lib/x86_64-linux-gnu/libjson-c.so* /lib/x86_64-linux-gnu/
COPY --from=bess-build /usr/lib/x86_64-linux-gnu/libbpf.so* /usr/lib/x86_64-linux-gnu/

ENV PYTHONPATH="/opt/bess"
WORKDIR /opt/bess/bessctl
ENTRYPOINT ["bessd", "-f"]

# Stage build bess golang pb
FROM golang:1.24.1-bookworm AS protoc-gen
RUN go install github.com/golang/protobuf/protoc-gen-go@latest

FROM bess-build AS go-pb
COPY --from=protoc-gen /go/bin/protoc-gen-go /bin
RUN mkdir /bess_pb && \
    protoc -I /usr/include -I /protobuf/ \
    /protobuf/*.proto /protobuf/ports/*.proto \
    --go_opt=paths=source_relative --go_out=plugins=grpc:/bess_pb

FROM bess-build AS py-pb
RUN pip install --no-cache-dir grpcio-tools==1.26
RUN mkdir /bess_pb && \
    python3 -m grpc_tools.protoc -I /usr/include -I /protobuf/ \
    /protobuf/*.proto /protobuf/ports/*.proto \
    --python_out=plugins=grpc:/bess_pb \
    --grpc_python_out=/bess_pb

FROM golang:1.24.1-bookworm AS pfcpiface-build
ARG GOFLAGS
WORKDIR /pfcpiface

COPY go.mod /pfcpiface/go.mod
COPY go.sum /pfcpiface/go.sum

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN if echo "$GOFLAGS" | grep -Eq "-mod=vendor"; then go mod download; fi

COPY . /pfcpiface
RUN CGO_ENABLED=0 go build $GOFLAGS -o /bin/pfcpiface ./cmd/pfcpiface

# Stage pfcpiface: runtime image of pfcpiface toward SMF/SPGW-C
FROM alpine:3.21 AS pfcpiface
COPY conf /opt/bess/bessctl/conf
COPY --from=pfcpiface-build /bin/pfcpiface /bin
ENTRYPOINT [ "/bin/pfcpiface" ]

# Stage pb: dummy stage for collecting protobufs
FROM scratch AS pb
COPY --from=bess-build /bess/protobuf /protobuf
COPY --from=go-pb /bess_pb /bess_pb

# Stage ptf-pb: dummy stage for collecting python protobufs
FROM scratch AS ptf-pb
COPY --from=bess-build /bess/protobuf /protobuf
COPY --from=py-pb /bess_pb /bess_pb

# Stage binaries: dummy stage for collecting artifacts
FROM scratch AS artifacts
COPY --from=bess /bin/bessd /
COPY --from=pfcpiface /bin/pfcpiface /
COPY --from=bess-build /bess /bess
