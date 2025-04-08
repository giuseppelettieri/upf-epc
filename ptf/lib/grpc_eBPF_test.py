# SPDX-License-Identifier: Apache-2.0
# Copyright 2021 Open Networking Foundation

from collections import namedtuple
from functools import wraps
from pprint import pprint

import grpc
from matplotlib.pyplot import flag
import ptf.testutils as testutils
from google.protobuf import text_format
from google.protobuf.any_pb2 import Any
from google.protobuf.json_format import MessageToDict
from ptf.base_tests import BaseTest

import bess_msg_pb2 as bess_msg
import module_msg_pb2 as module_msg
import upf_ebpf_msg_pb2 as ebpf_module_msg
import service_pb2_grpc as pb
import util_msg_pb2 as util_msg

# initialize useful variables
from trex_test import TrexTest

ACCESS = 0x1
CORE = 0x2
DST_ACCESS = ACCESS - 1
DST_CORE = CORE - 1

N3 = 0x0
N6 = 0x1
N9 = 0x2

ACTION_DROP = 0x1
ACTION_FORWARD = 0x2
ACTION_BUFFER = 0x4
ACTION_NOTIFY = 0x8

GATE_METER = 0x0
GATE_DROP = 0x5
GATE_UNMETER = 0x6

QFI_DEFAULT = 9

class GrpceBPFTest(BaseTest):
    """Define a base test for communicating with BESS over gRPC messages

    This base test contains setUp, tearDown and a library of functions
    for installing rules on BESS and reading metrics from BESS.
    """

    def setUp(self):
        self.pdrs = []
        self.fars = []
        self.appQers = []
        self.sessionQers = []

        # activate grpc connection to bess
        bess_server_addr = testutils.test_param_get("bess_upf_addr")
        self.channel = grpc.insecure_channel(target=bess_server_addr)
        self.bess_client = pb.BESSControlStub(self.channel)

    """
    API for reading metrics from BESS-UPF modules
    """

    def sendModuleCommand(self, request, timeout=5, raise_error=True):
        # TODO: print to write log file for easier debugging
        # print(text_format.MessageToString(request, as_one_line=True))
        response = self.bess_client.ModuleCommand(
            request,
            timeout=timeout,
        )
        if raise_error and response.error.code != 0:
            raise Exception(f"{request.name} {request.cmd}: {response.error.errmsg} (code {response.error.code})")
        return response

    def getPortStats(self, ifname):
        # to reveal bess interface names:
        # `docker exec -it bess ./bessctl`
        # `$ show port`
        req = bess_msg.GetPortStatsRequest(
            name = ifname + "Fast",
        )

        return self.bess_client.GetPortStats(req)

    def _readFlowMeasurement(self, module, clear, quantiles):
        # create request for flow measurements and send to bess
        request = module_msg.FlowMeasureCommandReadArg(
            clear=clear,
            latency_percentiles=quantiles,
            jitter_percentiles=quantiles,
            flag_to_read=2
        )
        any = Any()
        any.Pack(request)

        response = self.sendModuleCommand(
            bess_msg.CommandRequest(
                name = module,
                cmd = "read",
                arg = any,
            )
        )

        # unpack response and return results
        data = response.data
        msg = module_msg.FlowMeasureReadResponse()
        if data.Is(module_msg.FlowMeasureReadResponse.DESCRIPTOR):
            data.Unpack(msg)

        msg = MessageToDict(msg)
        if "statistics" in msg:
            return msg["statistics"]

        return msg

    def getSessionStats(self, q=[50, 90, 99], quiet=False):
        """
        Get QoS metrics from 3 different modules directly from BESS-UPF
        and return back in Python dictionary format
        """

        # Pre-Qos Measurement Module
        qosStatsInResp = self._readFlowMeasurement(
            module="preQosFlowMeasure",
            clear=True,
            quantiles=q,
        )
        if not quiet:
            print("Pre-QoS measurement module:")
            pprint(qosStatsInResp)
            print()

        # Post-Qos Downlink Measurement Module
        postDlQosStatsResp = self._readFlowMeasurement(
            module="postDLQosFlowMeasure",
            clear=True,
            quantiles=q,
        )
        if not quiet:
            print("Post-QoS downlink measurement module:")
            pprint(postDlQosStatsResp)
            print()

        # Post-Qos Uplink Measurement Module
        postUlQosStatsResp = self._readFlowMeasurement(
            module="postULQosFlowMeasure",
            clear=True,
            quantiles=q,
        )
        if not quiet:
            print("Post-QoS uplink measurement module:")
            pprint(postUlQosStatsResp)
            print()

        return {
            "preQos":    qosStatsInResp,
            "postDlQos": postDlQosStatsResp,
            "postUlQos": postUlQosStatsResp,
        }

    """ API for installing rules onto BESS-UPF over BESS gRPC calls """

    def createPDR(
        self,
        srcIface=0,
        tunnelIP4Dst=0,
        tunnelTEID=0,
        srcIP=0,
        dstIP=0,
        srcPort=0,
        dstPort=0,
        proto=0,
        srcIfaceMask=0,
        tunnelIP4DstMask=0,
        tunnelTEIDMask=0,
        srcIPMask=0,
        dstIPMask=0,
        srcPortMask=0,
        dstPortMask=0,
        protoMask=0,
        precedence=0,
        pdrID=0,
        fseID=0,
        fseidIP=0,
        ctrID=0,
        farID=0,
        qerIDList=[],
        needDecap=0,
        allocIPFlag=False,
    ):

        fields = (
            'srcIface',
            'tunnelIP4Dst',
            'tunnelTEID',
            'srcIP',
            'dstIP',
            'srcPort',
            'dstPort',
            'proto',

            'srcIfaceMask',
            'tunnelIP4DstMask',
            'tunnelTEIDMask',
            'srcIPMask',
            'dstIPMask',
            'srcPortMask',
            'dstPortMask',
            'protoMask',

            'precedence',
            'pdrID',
            'fseID',
            'fseidIP',
            'ctrID',
            'farID',
            'qerIDList',
            'needDecap',
            'allocIPFlag',
        )
        defaults = [
            srcIface,
            tunnelIP4Dst,
            tunnelTEID,
            srcIP,
            dstIP,
            srcPort,
            dstPort,
            proto,

            srcIfaceMask,
            tunnelIP4DstMask,
            tunnelTEIDMask,
            srcIPMask,
            dstIPMask,
            srcPortMask,
            dstPortMask,
            protoMask,

            precedence,
            pdrID,
            fseID,
            fseidIP,
            ctrID,
            farID,
            qerIDList,
            needDecap,
            allocIPFlag,
        ]

        PDR =  namedtuple('PDR', fields, defaults=defaults)
        return PDR()

    def createFAR(
        self,
        farID=0,
        fseID=0,
        fseidIP=0,
        dstIntf=0,
        sendEndMarker=False,
        applyAction=0,
        tunnelType=0,
        tunnelIP4Src=0,
        tunnelIP4Dst=0,
        tunnelTEID=0,
        tunnelPort=0,
    ):
        fields = (
            'farID',
            'fseID',
            'fseidIP',

            'dstIntf',
            'sendEndMarker',
            'applyAction',
            'tunnelType',
            'tunnelIP4Src',
            'tunnelIP4Dst',
            'tunnelTEID',
            'tunnelPort',
        )
        defaults = [
            farID,
            fseID,
            fseidIP,

            dstIntf,
            sendEndMarker,
            applyAction,
            tunnelType,
            tunnelIP4Src,
            tunnelIP4Dst,
            tunnelTEID,
            tunnelPort,
        ]

        FAR = namedtuple('FAR', fields, defaults=defaults)
        return FAR()

    def createQER(
        self,
        gate=0,
        qerID=0,
        qfi=QFI_DEFAULT,
        ulStatus=0,
        dlStatus=0,
        ulMbr=0,
        dlMbr=0,
        ulGbr=0,
        dlGbr=0,
        fseID=0,
        fseidIP=0,
        burstDurationMs=1000,
    ):
        fields = (
            'gate',
            'qerID',
            'qfi',
            'ulStatus',
            'dlStatus',
            'ulMbr',
            'dlMbr',
            'ulGbr',
            'dlGbr',
            'fseID',
            'fseidIP',
            'burstDurationMs',
        )
        defaults = [
            gate,
            qerID,
            qfi,
            ulStatus,
            dlStatus,
            ulMbr, # Kbps
            dlMbr, # Kbps
            ulGbr, # Kbps
            dlGbr, # Kbps
            fseID,
            fseidIP,
            burstDurationMs,
        ]
        QER = namedtuple('QER', fields, defaults=defaults)
        return QER()

    def addPDR(self, pdr, debug=False):
        for qerID in pdr.qerIDList:
            qerID = qerID
            break

        # parse params of PDR tuple into a wildcard match message to send to BESS
        f = ebpf_module_msg.UPFeBPFCommandAddPDRArg(
            priority = 4294967295 - pdr.precedence, # XXX: golang max 32 bit uint
            keys = ebpf_module_msg.PDRKeysData(
                srcIface = int(pdr.srcIface),
                tunnelIP4Dst = int(pdr.tunnelIP4Dst),
                tunnelTEID = int(pdr.tunnelTEID),
                ueIPsrcAddr = int(pdr.srcIP),
                inetIPdstAddr = int(pdr.dstIP),
                ueSrcPort = int(pdr.srcPort),
                inetSrcPort = int(pdr.dstPort),
                protoID = int(pdr.proto),
            ),
            masks = ebpf_module_msg.PDRKeysData(
                srcIface = int(pdr.srcIfaceMask),
                tunnelIP4Dst = int(pdr.tunnelIP4DstMask),
                tunnelTEID = int(pdr.tunnelTEIDMask),
                ueIPsrcAddr = int(pdr.srcIPMask),
                inetIPdstAddr = int(pdr.dstIPMask),
                ueSrcPort = int(pdr.srcPortMask),
                inetSrcPort = int(pdr.dstPortMask),
                protoID = int(pdr.protoMask),
            ),
            values = ebpf_module_msg.PDRValuesData(
                pdrID = int(pdr.pdrID),
                fseID = int(pdr.fseID),
                ctrID = int(pdr.ctrID),
                qerID = int(qerID),
                farID = int(pdr.farID),
            )
        )

        # store into Any() message protobuf type
        any = Any()
        any.Pack(f)

        # send request to UPF to add rule
        response = self.sendModuleCommand(
            bess_msg.CommandRequest(
                name = "upfeBPF",
                cmd = "add_pdr",
                arg = any
            )
        )
        if debug:
            print(response)

        self.pdrs.append(pdr)

    def delPDR(self, pdr, debug=False):
        # parse params of pdr into WildcardMatchCommandDeleteArg
        f = ebpf_module_msg.UPFeBPFCommandDeletePDRArg(
            keys = ebpf_module_msg.PDRKeysData(
                srcIface = int(pdr.srcIface),
                tunnelIP4Dst = int(pdr.tunnelIP4Dst),
                tunnelTEID = int(pdr.tunnelTEID),
                ueIPsrcAddr = int(pdr.srcIP),
                inetIPdstAddr = int(pdr.dstIP),
                ueSrcPort = int(pdr.srcPort),
                inetSrcPort = int(pdr.dstPort),
                protoID = int(pdr.proto),
            ),
            masks = ebpf_module_msg.PDRKeysData(
                srcIface = int(pdr.srcIfaceMask),
                tunnelIP4Dst = int(pdr.tunnelIP4DstMask),
                tunnelTEID = int(pdr.tunnelTEIDMask),
                ueIPsrcAddr = int(pdr.srcIPMask),
                inetIPdstAddr = int(pdr.dstIPMask),
                ueSrcPort = int(pdr.srcPortMask),
                inetSrcPort = int(pdr.dstPortMask),
                protoID = int(pdr.protoMask),
            )
        )

        # store into Any() message protobuf type
        any = Any()
        any.Pack(f)

        # send request to UPF to delete rule
        response = self.sendModuleCommand(
            bess_msg.CommandRequest(
                name = "upfeBPF",
                cmd = "delete_pdr",
                arg = any
            )
        )
        if debug:
            print(response)

    def _setActionValue(self, far):
        farForwardD = 0x0
        farForwardU = 0x1
        farDrop = 0x2
        farNotify = 0x3

        if (far.applyAction & ACTION_FORWARD) != 0:
            if far.dstIntf == DST_ACCESS:
                return farForwardD
            elif far.dstIntf == DST_CORE:
                return farForwardU
        elif (far.applyAction & ACTION_DROP) != 0:
            return farDrop
        elif (far.applyAction & ACTION_BUFFER) != 0 :
            return farNotify
        elif (far.applyAction & ACTION_NOTIFY) != 0:
            return farNotify

    def addFAR(self, far, debug=False):
        # set action value for far action
        action = self._setActionValue(far)

        # parse fields of far into ExactMatchCommandAddArg
        f = ebpf_module_msg.UPFeBPFCommandAddFARArg(
            keys = ebpf_module_msg.FARKeysData(
                farID = int(far.farID),
                fseID = int(far.fseID)
            ),
            values = ebpf_module_msg.FARValuesData(
                action = int(action),
                tunnelType = int(far.tunnelType),
                tunnelIP4Src = int(far.tunnelIP4Src),
                tunnelIP4Dst = int(far.tunnelIP4Dst),
                tunnelTEID = int(far.tunnelTEID),
                tunnelPort = int(far.tunnelPort)
            ),
        )

        # store into Any() message protobuf type
        any = Any()
        any.Pack(f)

        # send request to UPF to add rule
        response = self.sendModuleCommand(
            bess_msg.CommandRequest(
                name = "upfeBPF",
                cmd = "add_far",
                arg = any
            )
        )
        if debug:
            print(response)

        self.fars.append(far)

    def delFAR(self, far, debug=False):
        # parse params of far into ExactMatchCommandDeleteArg
        f = ebpf_module_msg.UPFeBPFCommandDeleteFARArg(
            keys = ebpf_module_msg.FARKeysData(
                farID = int(far.farID),
                fseID = int(far.fseID)
            ),
        )

        # store into Any() message protobuf type
        any = Any()
        any.Pack(f)

        # send request to UPF to delete rule
        response = self.sendModuleCommand(
            bess_msg.CommandRequest(
                name = "upfeBPF",
                cmd = "delete_far",
                arg = any
            )
        )
        if debug:
            print(response)

    def _calcRates(self, ulGbr, ulMbr, dlGbr, dlMbr, burstDuration, minBurstSize=1):
        # 0 is not a valid rate or burst size, the minimum is 1
        # calculate uplink burst sizes
        ulCbs = (float(ulGbr) * 1000 / 8) * (burstDuration / 1000)
        ulPbs = (float(ulMbr) * 1000 / 8) * (burstDuration / 1000)
        ulCbs = max(ulCbs, minBurstSize)
        ulPbs = max(ulPbs, minBurstSize)
        ulEbs = ulPbs
        if ulMbr != 0 or ulGbr != 0:
            ulCir = max(ulGbr * 1000 / 8, 1)
            ulPir = max(ulMbr * 1000 / 8, ulCir)
        else:
            ulCir = 1
            ulPir = 1

        # calculate downlink burst sizes
        dlCbs = (float(dlGbr) * 1000 / 8) * (burstDuration / 1000)
        dlPbs = (float(dlMbr) * 1000 / 8) * (burstDuration / 1000)
        dlCbs = max(dlCbs, minBurstSize)
        dlPbs = max(dlPbs, minBurstSize)
        dlEbs = dlPbs
        if dlMbr != 0 or dlGbr != 0:
            dlCir = max(dlGbr * 1000 / 8, 1)
            dlPir = max(dlMbr * 1000 / 8, dlCir)
        else:
            dlCir = 1
            dlPir = 1

        fields = [
            'ulCbs', 'ulPbs', 'ulEbs', 'ulCir', 'ulPir',
            'dlCbs', 'dlPbs', 'dlEbs', 'dlCir', 'dlPir',
        ]
        defaults = [
            ulCbs, ulPbs, ulEbs, ulCir, ulPir, dlCbs, dlPbs, dlEbs, dlCir, dlPir,
        ]

        rates = namedtuple('rates', fields, defaults=defaults)
        return rates()

    def addApplicationQER(self, qer, debug=False):
        ''' installs uplink and downlink application QER '''
        rates = self._calcRates(
            qer.ulGbr,
            qer.ulMbr,
            qer.dlGbr,
            qer.dlMbr,
            qer.burstDurationMs,
        )

        if debug:
            print(rates)

        # construct UL/DL QosCommandAddArg's and send to BESS
        for srcIface in [ACCESS, CORE]:
            f = ebpf_module_msg.UPFeBPFCommandAddAppQoSArg(
                qos_val = ebpf_module_msg.QoSValues(
                    cir = int(rates.ulCir) if srcIface == ACCESS else int(rates.dlCir),
                    pir = int(rates.ulPir) if srcIface == ACCESS else int(rates.dlPir),
                    cbs = int(rates.ulCbs) if srcIface == ACCESS else int(rates.dlCbs),
                    pbs = int(rates.ulPbs) if srcIface == ACCESS else int(rates.dlPbs),
                    ebs = int(rates.ulEbs) if srcIface == ACCESS else int(rates.dlEbs),
                ),
                keys = ebpf_module_msg.AppQoSKeysData(
                    srcIface = srcIface,
                    qerID = int(qer.qerID),
                    fseID = int(qer.fseID)
                ),
                values = ebpf_module_msg.AppQoSValuesData(
                    qfiID = int(qer.qfi)
                ),
            )

            any = Any()
            any.Pack(f)

            response = self.sendModuleCommand(
                bess_msg.CommandRequest(
                    name = "upfeBPF",
                    cmd = "add_app_qos",
                    arg = any
                )
            )
            if debug:
                print(response)

        self.appQers.append(qer)

    def delApplicationQER(self, qer, debug=False):
        ''' deletes uplink and downlink application QER '''
        for srcIface in [ACCESS, CORE]:
            f = ebpf_module_msg.UPFeBPFCommandDelAppQoSArg(
                keys = ebpf_module_msg.AppQoSKeysData(
                    srcIface = srcIface,
                    qerID = int(qer.qerID),
                    fseID = int(qer.fseID)
                ),
            )
            any = Any()
            any.Pack(f)

            response = self.sendModuleCommand(
                bess_msg.CommandRequest(
                    name = "upfeBPF",
                    cmd = "delete_app_qos",
                    arg = any
                )
            )
            if debug:
                print(response)

    def addSessionQER(self, qer, debug=False):
        ''' installs uplink and downlink session QER '''
        rates = self._calcRates(
            qer.ulGbr,
            qer.ulMbr,
            qer.dlGbr,
            qer.dlMbr,
            qer.burstDurationMs,
        )

        # construct UL/DL QosCommandAddArg's and send to BESS
        for srcIface in [ACCESS, CORE]:
            f = ebpf_module_msg.UPFeBPFCommandAddSessionQoSArg(
                qos_val = ebpf_module_msg.QoSValues(
                    cir = int(rates.ulCir) if srcIface == ACCESS else int(rates.dlCir),
                    pir = int(rates.ulPir) if srcIface == ACCESS else int(rates.dlPir),
                    cbs = int(rates.ulCbs) if srcIface == ACCESS else int(rates.dlCbs),
                    pbs = int(rates.ulPbs) if srcIface == ACCESS else int(rates.dlPbs),
                    ebs = int(rates.ulEbs) if srcIface == ACCESS else int(rates.dlEbs),
                ),
                keys = ebpf_module_msg.SessionQoSKeysData(
                    srcIface = srcIface,
                    qerID = int(qer.qerID),
                    fseID = int(qer.fseID)
                ),
            )

            any = Any()
            any.Pack(f)

            response = self.sendModuleCommand(
                bess_msg.CommandRequest(
                    name = "upfeBPF",
                    cmd = "add_session_qos",
                    arg = any
                )
            )
            if debug:
                print(response)

        self.sessionQers.append(qer)

    def delSessionQER(self, qer, debug=False):
        ''' deletes uplink and downlink session QER '''
        for srcIface in [ACCESS, CORE]:
            f = ebpf_module_msg.UPFeBPFCommandDelSessionQoSArg(
                keys = ebpf_module_msg.SessionQoSKeysData(
                    srcIface = srcIface,
                    qerID = int(qer.qerID),
                    fseID = int(qer.fseID)
                ),
            )
            any = Any()
            any.Pack(f)

            response = self.sendModuleCommand(
                bess_msg.CommandRequest(
                    name = "upfeBPF",
                    cmd = "delete_session_qos",
                    arg = any
                )
            )
            if debug:
                print(response)

    def tearDown(self):
        print("Closing gRPC channel...")
        self.channel.close()

""" Functionality for flow cleanup after tests """

def _cleanupRules(test):
    for pdr in test.pdrs:
        test.delPDR(pdr)

    for far in test.fars:
        test.delFAR(far)

    for aQer in test.appQers:
        test.delApplicationQER(aQer)

    for sQer in test.sessionQers:
        test.delSessionQER(sQer)

    return

def autocleanup(f):
    """
    Decorator for cleaning up installed rules after a PTF test's
    completion
    """
    @wraps(f)
    def handle(*args, **kwargs):
        test = args[0]
        assert isinstance(test, GrpceBPFTest)

        try:
            # Clear QoS stats on BESS before test runs
            # test.getSessionStats(quiet=True)

            return f(*args, **kwargs)

        finally:
            # Reset Trex streams, stats, etc.
            if isinstance(test, TrexTest):
                test.reset()

            # cleanup rules for pdrs, fars, app qers and session qers
            _cleanupRules(test)

            # clear lists
            test.pdrs = []
            test.fars = []
            test.appQers = []
            test.sessionQers = []

    return handle
