# SPDX-License-Identifier: Apache-2.0
# Copyright 2021 Open Networking Foundation

import time
from ipaddress import IPv4Address
from pprint import pprint

from scapy.layers.l2 import Ether
from pkt_utils import GTPU_PORT, pkt_add_gtpu
from trex_test import TrexTest
from grpc_eBPF_test import *
from trex_utils import *
from progressbar import ProgressBar, Percentage, Bar, ETA, AdaptiveETA

from trex_stl_lib.api import (
    STLVM,
    STLPktBuilder,
    STLStream,
    STLTXCont,
    STLFlowLatencyStats,
)
import ptf.testutils as testutils

widgets = [Percentage(),
           ' ', Bar(),
           ' ', ETA(),
           ' ', AdaptiveETA()]

ACCESS_DEST_MAC = "f8:f2:1e:b2:43:00"
CORE_DEST_MAC = "f8:f2:1e:b2:43:01"

# Port setup
TREX_SENDER_PORT = 0
TREX_RECEIVER_PORT = 1
BESS_ACCESS_PORT = 0
BESS_CORE_PORT = 1

# test specs
DURATION = 60
RATE = 100_000  # 100 Kpps
# RATE = 4_000_000  # 4 Mpps
UE_COUNT = 10_000 # 10k UEs
PKT_SIZE = 128

N3_IP = IPv4Address('10.128.13.29')
PDN_IP = IPv4Address("11.1.1.129")
ENB_IP = IPv4Address('10.27.19.99')

class DownlinkPerformanceBaselineTest(TrexTest, GrpceBPFTest):
    """
    Performance baseline linerate test generating downlink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

    @autocleanup
    def runTest(self):
        n3TEID = 0
        mbr_bps = 40000 * M # 40Gbps
        mbr_kbps = mbr_bps / K
        burst_ms = 10

        startIP = IPv4Address('16.0.0.1')
        endIP = startIP + UE_COUNT - 1

        pbar = ProgressBar(widgets=widgets, maxval=UE_COUNT).start()
        # program UPF for downlink traffic by installing PDRs and FARs
        print("Installing PDRs and FARs...")
        for i in range(UE_COUNT):
            # install N6 DL PDR to match UE dst IP
            pdrDown = self.createPDR(
                srcIface = CORE,
                dstIP = int(startIP + i),
                srcIfaceMask = 0xFF,
                dstIPMask = 0xFFFFFFFF,
                precedence = 255,
                fseID = n3TEID + i + 1, # start from 1
                ctrID = 0,
                farID = i,
                qerIDList = [1],
                needDecap = 0,
            )
            self.addPDR(pdrDown)

            # install N6 DL FAR for encap
            farDown = self.createFAR(
                farID = i,
                fseID = n3TEID + i + 1, # start from 1
                applyAction = ACTION_FORWARD,
                dstIntf = DST_ACCESS,
                tunnelType = 0x1,
                tunnelIP4Src = int(N3_IP),
                tunnelIP4Dst = int(ENB_IP), # only one eNB to send to downlink
                tunnelTEID = 0,
                tunnelPort = GTPU_PORT,
            )
            self.addFAR(farDown)

            # install N6 DL/UL application QER
            qer = self.createQER(
                gate=GATE_METER,
                qerID=1,
                fseID=n3TEID + i + 1,
                ulMbr=mbr_kbps,
                dlMbr=mbr_kbps,
                burstDurationMs=burst_ms,
            )
            self.addApplicationQER(qer)

            pbar.update(i)

        # set up trex to send traffic thru UPF
        print("Setting up TRex client...")
        vm = STLVM()
        vm.var(
            name="dst",
            min_value=str(startIP),
            max_value=str(endIP),
            size=4,
            op="random",
        )
        vm.write(fv_name="dst", pkt_offset="IP.dst")
        vm.fix_chksum()

        pkt = testutils.simple_udp_packet(
            pktlen=PKT_SIZE,
            eth_dst=CORE_DEST_MAC,
            with_udp_chksum=False,
        )
        stream = STLStream(
            packet=STLPktBuilder(pkt=pkt, vm=vm),
            mode=STLTXCont(pps=RATE),
            flow_stats=STLFlowLatencyStats(pg_id=BESS_ACCESS_PORT),
        )
        self.trex_client.add_streams(stream, ports=[BESS_CORE_PORT])
        self.trex_client.clear_stats()
        self.trex_client.set_port_attr(ports=[BESS_ACCESS_PORT], promiscuous=True)

        print("Running traffic...")
        s_time = time.time()
        self.trex_client.start(
            ports=[BESS_CORE_PORT],
            duration=DURATION,
        )

        self.trex_client.wait_on_traffic(ports=[BESS_CORE_PORT])
        duration = time.time() - s_time
        print(f"Duration was {duration}")

        trex_stats = self.trex_client.get_stats()
        print(trex_stats)
        lat_stats = get_latency_stats(BESS_ACCESS_PORT, trex_stats)
        flow_stats = get_flow_stats(BESS_ACCESS_PORT, trex_stats)

        tx_packets_rate = (flow_stats.tx_packets/duration)/1000000
        rx_packets_rate = (flow_stats.rx_packets/duration)/1000000
        
        print(f"Sent packets at rate: {tx_packets_rate:.2f} Mpps")
        print(f"Received packets at rate: {rx_packets_rate:.2f} Mpps")

        print(f"Average latency is {lat_stats.average} us")
        print(f"50th %ile (median) latency is {lat_stats.percentile_50} us")
        print(f"99.9th %ile latency is {lat_stats.percentile_99_9} us")
        print(f"Jitter is {lat_stats.jitter} us")

        return


class UplinkPerformanceBaselineTest(TrexTest, GrpceBPFTest):
    """
    Performance baseline linerate test generating uplink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

    @autocleanup
    def runTest(self):
        n3TEID = 0

        mbr_bps = 40000 * M # 40Gbps
        mbr_kbps = mbr_bps / K
        burst_ms = 10

        startIP = IPv4Address('16.0.0.1')
        endIP = startIP + UE_COUNT - 1

        pbar = ProgressBar(widgets=widgets, maxval=UE_COUNT).start()
        # program UPF for uplink traffic by installing PDRs and FARs
        print("Installing PDRs and FARs...")
        for i in range(UE_COUNT):
            pdrUp = self.createPDR(
                srcIface = ACCESS,
                srcIP = int(startIP + i),
                tunnelIP4Dst=int(N3_IP),
                tunnelTEID=1,
                srcIfaceMask = 0xFF,
                srcIPMask=0xFFFFFFFF,
                tunnelIP4DstMask=0xFFFFFFFF,
                tunnelTEIDMask=0xFFFF,
                precedence = 255,
                fseID = n3TEID + i + 1, # start from 1
                ctrID = 0,
                farID = i,
                qerIDList = [1],
                needDecap = 1,
            )
            self.addPDR(pdrUp)

            farUp = self.createFAR(
                farID = i,
                fseID = n3TEID + i + 1, # start from 1
                applyAction = ACTION_FORWARD,
                dstIntf = DST_CORE,
            )
            self.addFAR(farUp)

            qer = self.createQER(
                gate=GATE_METER,
                qerID=1,
                fseID=n3TEID + i + 1,
                ulMbr=mbr_kbps,
                dlMbr=mbr_kbps,
                burstDurationMs=burst_ms,
            )
            self.addApplicationQER(qer)

            pbar.update(i)

        # set up trex to send traffic thru UPF
        print("Setting up TRex client...")
        vm = STLVM()
        vm.var(
            name="inner_src",
            min_value=str(startIP),
            max_value=str(endIP),
            size=4,
            op="random",
        )

        if (UE_COUNT > 65535 - 1024):
            vm.var(
                name="srcPort",
                min_value=1024,
                max_value=int(65534),
                size=2,
                op="random",
            )
        else:
            vm.var(
                name="srcPort",
                min_value=1024,
                max_value=int(1024 + UE_COUNT),
                size=2,
                op="random",
            )
        vm.write(fv_name="srcPort", pkt_offset="UDP.sport")
        vm.write(fv_name="inner_src", pkt_offset=62)
        vm.fix_chksum()

        pkt = testutils.simple_udp_packet(
            pktlen=PKT_SIZE,
            eth_dst=ACCESS_DEST_MAC,
            ip_dst=str(PDN_IP),
            with_udp_chksum=False,
        )

        gtpu_pkt = pkt_add_gtpu(
            pkt=pkt,
            out_ipv4_src=str(ENB_IP),
            out_ipv4_dst=str(N3_IP),
            teid=1,
        )

        stream = STLStream(
            packet=STLPktBuilder(pkt=gtpu_pkt, vm=vm),
            mode=STLTXCont(pps=RATE),
            flow_stats=STLFlowLatencyStats(pg_id=BESS_CORE_PORT),
        )
        self.trex_client.add_streams(stream, ports=[BESS_ACCESS_PORT])
        self.trex_client.clear_stats()
        self.trex_client.set_port_attr(ports=[BESS_CORE_PORT], promiscuous=True)

        print("Running traffic...")
        s_time = time.time()
        self.trex_client.start(
            ports=[BESS_ACCESS_PORT],
            duration=DURATION,
        )

        self.trex_client.wait_on_traffic(ports=[BESS_ACCESS_PORT])
        duration = time.time() - s_time
        print(f"Duration was {duration}")

        trex_stats = self.trex_client.get_stats()
        print(trex_stats)
        lat_stats = get_latency_stats(BESS_CORE_PORT, trex_stats)
        flow_stats = get_flow_stats(BESS_CORE_PORT, trex_stats)

        tx_packets_rate = (flow_stats.tx_packets/duration)/1000000
        rx_packets_rate = (flow_stats.rx_packets/duration)/1000000

        print(f"Sent packets at rate: {tx_packets_rate:.2f} Mpps")
        print(f"Received packets at rate: {rx_packets_rate:.2f} Mpps")

        print(f"Average latency is {lat_stats.average} us")
        print(f"50th %ile (median) latency is {lat_stats.percentile_50} us")
        print(f"99.9th %ile latency is {lat_stats.percentile_99_9} us")
        print(f"Jitter is {lat_stats.jitter} us")

        return

