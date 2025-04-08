#!/bin/bash

set -x

# Use 114 for second device
sudo docker run --name pktgen -td --restart unless-stopped --cpuset-cpus=0,2,4,6 -p 0.0.0.0:8000:8000 \
                --ulimit memlock=-1 --cap-add IPC_LOCK --privileged -v /dev/hugepages:/dev/hugepages \
                -v "$PWD/conf":/opt/bess/bessctl/conf --net host \
                upf-epc-bess:"$(<VERSION)" -grpc-url=0.0.0.0:10514

sleep 20
sudo docker exec -d -it pktgen ./bessctl http 0.0.0.0 8000
sudo docker exec -it -d pktgen ./bessctl run custom_pktgen
