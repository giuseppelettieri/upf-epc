# SPDX-License-Identifier: Apache-2.0
# Copyright 2021 Open Networking Foundation

import time
from ipaddress import IPv4Address
from pprint import pprint

from scapy.layers.l2 import Ether
from pkt_utils import GTPU_PORT, pkt_add_gtpu
from trex_test import TrexTest
from grpc_test import *
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
DURATION = 10
RATE = 100_000  # 100 Kpps
UE_COUNT = 10_000 # 10k UEs
PKT_SIZE = 64

N3_IP = IPv4Address('10.128.13.29')
ENB_IP = IPv4Address('11.1.1.129')

class DownlinkRuleInsertionTest(GrpcTest):
    """
    Performance baseline linerate test generating downlink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

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
                gate=GATE_UNMETER,
                qerID=1,
                fseID=n3TEID + i + 1,
                ulMbr=mbr_kbps,
                dlMbr=mbr_kbps,
                burstDurationMs=burst_ms,
            )
            self.addApplicationQER(qer)

            pbar.update(i)

        return

class DownlinkRuleDeletionTest(GrpcTest):
    """
    Performance baseline linerate test generating downlink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

    def runTest(self):
        n3TEID = 0
        mbr_bps = 40000 * M # 40Gbps
        mbr_kbps = mbr_bps / K
        burst_ms = 10

        startIP = IPv4Address('16.0.0.1')
        endIP = startIP + UE_COUNT - 1

        pbar = ProgressBar(widgets=widgets, maxval=UE_COUNT).start()
        # program UPF for downlink traffic by installing PDRs and FARs
        print("Deleting PDRs and FARs...")
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
            self.delPDR(pdrDown)

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
            self.delFAR(farDown)

            # install N6 DL/UL application QER
            qer = self.createQER(
                gate=GATE_UNMETER,
                qerID=1,
                fseID=n3TEID + i + 1,
                ulMbr=mbr_kbps,
                dlMbr=mbr_kbps,
                burstDurationMs=burst_ms,
            )
            self.delApplicationQER(qer)

            pbar.update(i)

        return


class UplinkRuleInsertionTest(GrpcTest):
    """
    Performance baseline linerate test generating uplink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

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

        return

class UplinkRuleDeletionTest(GrpcTest):
    """
    Performance baseline linerate test generating uplink traffic at 1 Mpps
    with 10k UE IPs, asserting expected performance of BESS-UPF as reported by
    TRex traffic generator.
    """

    def runTest(self):
        n3TEID = 0

        mbr_bps = 40000 * M # 40Gbps
        mbr_kbps = mbr_bps / K
        burst_ms = 10

        startIP = IPv4Address('16.0.0.1')
        endIP = startIP + UE_COUNT - 1

        pbar = ProgressBar(widgets=widgets, maxval=UE_COUNT).start()

        # program UPF for uplink traffic by installing PDRs and FARs
        print("Deleting PDRs and FARs...")
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
            self.delPDR(pdrUp)

            farUp = self.createFAR(
                farID = i,
                fseID = n3TEID + i + 1, # start from 1
                applyAction = ACTION_FORWARD,
                dstIntf = DST_CORE,
            )
            self.delFAR(farUp)

            qer = self.createQER(
                gate=GATE_METER,
                qerID=1,
                fseID=n3TEID + i + 1,
                ulMbr=mbr_kbps,
                dlMbr=mbr_kbps,
                burstDurationMs=burst_ms,
            )
            self.delApplicationQER(qer)

            pbar.update(i)

        return
