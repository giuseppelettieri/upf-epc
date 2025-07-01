# SPDX-License-Identifier: Apache-2.0
# Copyright 2020-present Open Networking Foundation
# Copyright 2019-present Intel Corporation

# Before start the build create the necessary interfaces
# for example like this:
#     sudo ip link add link enp4s0f1 name ens4f0 type vlan id 2
#     sudo ip link add link enp4s0f1 name ens4f1 type vlan id 3
#     sudo ip link set ens4f0 up
#     sudo ip link set ens4f1 up
#     sudo ip addr add 198.18.0.1/30 dev ens4f0
#     sudo ip addr add 198.19.0.1/30 dev ens4f1

# Stage bess: creates the runtime image of BESS
FROM ubuntu:24.04 AS bess
ARG CPU=native
ENV PLUGINS_DIR=plugins

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
        ca-certificates software-properties-common \
        sudo kmod python3-pyverbs curl python-is-python3 \
        linux-tools-common linux-tools-generic linux-headers-`uname -r` build-essential \
        python3-pyverbs pkg-config git make apt-transport-https \
        g++ libunwind8-dev liblzma-dev zlib1g-dev \
        libpcap-dev libssl-dev libnuma-dev \
        python3-protobuf python3-grpcio python3-scapy libgflags-dev libgoogle-glog-dev \
        libgraph-easy-perl libgtest-dev \
        libc-ares-dev libbenchmark-dev \
        libgtest-dev wget autoconf \
        automake cmake libtool \
        make ninja-build patch \
        unzip virtualenv zip tar meson-1.5 \
        libz-dev libnl-3-dev gcc g++ gcc-multilib clang llvm lld m4 \
        ethtool libbsd0 libbsd-dev libelf1 libelf-dev libjson-c-dev libnl-3-dev libnl-cli-3-dev libnuma-dev \
        libpcap0.8 libcap-dev libsystemd-dev libgflags-dev

RUN ln -s /usr/include/x86_64-linux-gnu/asm /usr/include/asm

## Mellanox OFED Driver
ARG ENABLE_MLX
COPY install_mlx_ofed.sh .
RUN ./install_mlx_ofed.sh

WORKDIR /bpftool
COPY xdp-plugin xdp-scripts
RUN ./xdp-scripts/install-dependencies.sh && \
    rm -rf /bpftool

WORKDIR /libxdp
ARG LIBXDP_VER=libxdp-cpp-v1.5.0
RUN git clone --recurse-submodules https://github.com/alefais/xdp-tools.git --branch ${LIBXDP_VER} --single-branch && \
    cd xdp-tools && \
    FORCE_SUBDIR_LIBBPF=1 ./configure && \
    make libxdp && PREFIX=/usr make libxdp install && \
    ldconfig && \
    echo -e "Linux libxdp installed." && pkg-config --modversion libxdp

# linux ver should match target machine's kernel
WORKDIR /libbpf
ARG LIBBPF_VER=v0.7.0
RUN git clone https://github.com/libbpf/libbpf.git --branch ${LIBBPF_VER} --single-branch && \
    cd libbpf/src && \
    LIBDIR=/usr/lib/x86_64-linux-gnu/ make install && LIBDIR=/usr/lib/x86_64-linux-gnu/ make install_uapi_headers && \
    ldconfig && \
    export PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig && \
    echo -e "Linux libbpf installed." && pkg-config --modversion libbpf

# Setup llvm and clang version to the older release 12.0.0
RUN wget http://archive.ubuntu.com/ubuntu/pool/main/libf/libffi/libffi7_3.3-4_amd64.deb && dpkg -i libffi7_3.3-4_amd64.deb
RUN wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key|sudo apt-key add - && \
    add-apt-repository -y "deb http://apt.llvm.org/focal/ llvm-toolchain-focal-12 main" && \
    apt-get update && apt-get install -y clang-12 clang-tools-12 clang-format-12 llvm-12 llvm-12-dev llvm-12-tools llvm-12-runtime && \
    update-alternatives --install /usr/bin/clang clang /usr/bin/clang-12 100 \
    --slave /usr/bin/clang++ clang++ /usr/bin/clang++-12 \
    --slave /usr/bin/llc llc /usr/bin/llc-12 && \
    update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-12 100

# Setup gcc and g++ version to the older release 10.5.0
RUN apt-get update && apt-get install -y gcc-10 g++-10
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 100 \
    --slave /usr/bin/g++ g++ /usr/bin/g++-10

WORKDIR /grpc
ARG GRPC_VER=v1.44.0
RUN git clone https://github.com/grpc/grpc --branch ${GRPC_VER} --single-branch && \
    cd /grpc/grpc && git submodule update --init --recursive && \
    mkdir -p cmake/build && cd cmake/build && \
    cmake ../.. -DgRPC_INSTALL=ON               \
                -DCMAKE_BUILD_TYPE=Release      \
                -DgRPC_ABSL_PROVIDER=module     \
                -DgRPC_CARES_PROVIDER=module    \
                -DgRPC_PROTOBUF_PROVIDER=module \
                -DgRPC_RE2_PROVIDER=module      \
                -DgRPC_SSL_PROVIDER=package     \
                -DgRPC_ZLIB_PROVIDER=package && \
    make -j$(getconf _NPROCESSORS_ONLN) && make install

RUN cd /grpc/grpc/third_party/protobuf && \
    git submodule update --init --recursive && \
    ./autogen.sh && ./configure && \
    make -j$(getconf _NPROCESSORS_ONLN) && make install && ldconfig

# Restore gcc and g++ version 13.3.0 (default on Ubuntu 24.04)
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-13 150 \
    --slave /usr/bin/g++ g++ /usr/bin/g++-13

# BESS pre-reqs

# Build and install CNDP shared libraries + Build and install CNDP static libraries
WORKDIR /cndp
RUN git clone https://github.com/CloudNativeDataPlane/cndp.git && \
    cd cndp && \
    sed -e "155s#.*#add_project_arguments('-I/cndp/lib/include/', language: 'c')#" -i meson.build && \
    make && make install && make static_build=1 rebuild install && \
    cp -r usr/local/include/cndp/* /usr/local/include && \
    cp -r usr/local/lib/* /usr/local/lib && \
    cp -r usr/local/bin/* /usr/local/bin

# Set CNDP PKG_CONFIG_PATH
ENV PKG_CONFIG_PATH=/usr/lib64/pkgconfig:/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/lib/pkgconfig

WORKDIR /python-iptools
RUN git clone https://github.com/bd808/python-iptools.git && \
    cd python-iptools && python setup.py install

WORKDIR /bess
ARG BESS_COMMIT=seb
RUN git clone https://github.com/DanieleDiBella99/bess.git --branch ${BESS_COMMIT} --single-branch . && \
    sed -e "74s/$/ libcndp/" -i core/Makefile && \
    cp -a protobuf /protobuf

# Build DPDK
RUN ./build.py dpdk

WORKDIR /bess
RUN mkdir -p plugins && \
    mv sample_plugin plugins/sample_plugin

COPY upf-ebpf upf-ebpf
COPY upf-ebpf/protobuf/upf_ebpf_msg.proto /protobuf/
RUN mv upf-ebpf plugins/upf-ebpf

## Network Token
ARG ENABLE_NTF
ARG NTF_COMMIT=master
COPY scripts/install_ntf.sh .
RUN ./install_ntf.sh

RUN ./plugins/upf-ebpf/scripts/install-deps.sh && \
    cp -r plugins/upf-ebpf /bess && \
    cp -r plugins/sample_plugin /bess && \
    echo -e "Check Linux libxdp version: expected v1.5.0." && pkg-config --modversion libxdp && \
    echo -e "Check Linux libbpf version: expected v0.7.0." && pkg-config --modversion libbpf

# FIX error from meson-private/install.dat
RUN cd /bess/deps/dpdk-20.11.4/build && meson setup --reconfigure /bess/deps/dpdk-20.11.4
# FIX too many arguments to function ‘netif_napi_add’
RUN sed -e "176s/sn_poll, NAPI_POLL_WEIGHT/sn_poll/" -i /bess/core/kmod/sn_netdev.c
# FIX implicit declaration of function ‘napi_reschedule’; did you mean ‘napi_schedule’?
RUN sed -e "497s/napi_reschedule/napi_schedule/" -i /bess/core/kmod/sn_netdev.c

RUN cd /bess && \
    ./build.py --plugin sample_plugin && \
    ./build.py --plugin upf-ebpf && \
    mkdir -p /bin/modules && \
    mkdir -p /opt/bess && \
    mkdir -p /pb && \
    cp bin/bessd /bin && \
    cp -r core/modules/* /bin/modules && \
    cp -r bessctl pybess /opt/bess && \
    cp -r core/pb/* /pb && \
    mkdir -p /opt/bess/bessctl/kmod && \
    cp -r /bess/core/kmod/* /opt/bess/bessctl/kmod

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get --purge remove -y gcc

COPY conf /opt/bess/bessctl/conf
RUN cp -r /bess/sample_plugin /opt/bess/bessctl && \
    cp -r /bess/upf-ebpf /opt/bess/bessctl
# FIX problem related to glibc-2.38 not found
RUN ln -s /opt/bess/bessctl/bessctl /bin && \
    ln -s /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libc-2.38.so

ENV PYTHONPATH="/opt/bess"
WORKDIR /opt/bess/bessctl
ENTRYPOINT ["bessd", "-f"]

# Stage build bess golang pb
FROM ubuntu:24.04 AS protoc-gen
ARG CPU=native
RUN apt-get update && apt-get install -y golang
RUN go install github.com/golang/protobuf/protoc-gen-go@latest

FROM bess AS go-pb
COPY --from=protoc-gen /go/bin/protoc-gen-go /bin
RUN mkdir /bess_pb && \
    protoc -I /usr/include -I /protobuf/ \
    /protobuf/*.proto /protobuf/ports/*.proto \
    --go_opt=paths=source_relative --go_out=plugins=grpc:/bess_pb

FROM bess AS py-pb
RUN pip install --no-cache-dir grpcio-tools==1.26
RUN mkdir /bess_pb && \
    python3 -m grpc_tools.protoc -I /usr/include -I /protobuf/ \
    /protobuf/*.proto /protobuf/ports/*.proto \
    --python_out=plugins=grpc:/bess_pb \
    --grpc_python_out=/bess_pb

FROM ubuntu:24.04 AS pfcpiface-build
RUN apt-get update && apt-get install -y golang
RUN apt-get update && apt-get install -y --reinstall ca-certificates && \
    update-ca-certificates
ARG GOFLAGS
ENV GOINSECURE="*"
WORKDIR /pfcpiface

COPY go.mod /pfcpiface/go.mod
COPY go.sum /pfcpiface/go.sum

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN if echo "$GOFLAGS" | grep -Eq "-mod=vendor"; then go mod download; fi

COPY . /pfcpiface
RUN CGO_ENABLED=0 go build $GOFLAGS -o /bin/pfcpiface ./cmd/pfcpiface

# Stage pfcpiface: runtime image of pfcpiface toward SMF/SPGW-C
FROM ubuntu:24.04 AS pfcpiface
COPY conf /opt/bess/bessctl/conf
COPY --from=bess /bess/sample_plugin /opt/bess/bessctl
COPY --from=bess /bess/upf-ebpf /opt/bess/bessctl
COPY --from=pfcpiface-build /bin/pfcpiface /bin
ENTRYPOINT [ "/bin/pfcpiface" ]

# Stage pb: dummy stage for collecting protobufs
FROM scratch AS pb
COPY --from=bess /bess/protobuf /protobuf
COPY --from=go-pb /bess_pb /bess_pb

# Stage ptf-pb: dummy stage for collecting python protobufs
FROM scratch AS ptf-pb
COPY --from=bess /bess/protobuf /protobuf
COPY --from=py-pb /bess_pb /bess_pb

# Stage binaries: dummy stage for collecting artifacts
FROM scratch AS artifacts
COPY --from=bess /bin/bessd /
COPY --from=pfcpiface /bin/pfcpiface /
COPY --from=bess /bess /bess
