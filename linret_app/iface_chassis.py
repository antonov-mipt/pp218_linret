import logging, queue, threading, time, copy
from rawsocketpy import RawSocket
from config import PROGRAM_CONFIG
from protocol.cha_enums import *
from protocol.cs_enums import *
from protocol.cha_structs import *
from protocol.cs_structs import *
from protocol.cha_stream_structs import *

class IFACE_CHASSIS:
    def __init__(self, program_params:PROGRAM_CONFIG):
        self.log = logging.getLogger('CHAS')
        self.shutdown = False
        self.program_params = program_params
        self.eth = program_params.get_eth_iface()
        self.chassis_mac = program_params.get_chassis_mac()
        self.chassis_connected = False
        self.rx_thread = threading.Thread(target=self.recv_loop)
        self.tx_thread = threading.Thread(target=self.send_loop)
        self.last_rx_activity = 0
        self.last_stats_send = 0
        self._queue = queue.Queue(maxsize=50)
        self.dbg_stats = {
            'tx_ctr': 0,
            'rx_ctr': 0,
            'queue_full_drops': 0,
            'inpt_hdr_errors': 0,
            'extra_bytes_recvd': 0,
            'serialize_errors': 0,
            'un_serialize_errors': 0,
            'tx_sock_exceptions': 0,
            'if_type_drived_recvs': 0,
            'chunk_sequence_error': 0
        }

    def run(self):
        self.rx_thread.start()
        self.tx_thread.start()

    def join(self):
        self.rx_thread.join()
        self.tx_thread.join()

    def register_msg_handlers(self, to_core, to_str, to_mon):
        self.send_msg_to_core = to_core
        self.send_msg_to_streamproc = to_str
        self.send_msg_to_mon = to_mon

    def send_msg_to_chassis(self, msg):
        try: self._queue.put(msg, timeout = 1)
        except queue.Full: self.dbg_stats['queue_full_drops'] += 1

    def handshaker(self, now):
        if now - self.last_rx_activity > 3:
            if self.chassis_connected:
                self.log.warning("Chassis lost")
                self.chassis_connected = False
            self.send_msg_to_chassis(CHA_HANDSHAKE_REQUEST())
            self.last_rx_activity = now

    def stats_sender(self, now):
        if now - self.last_stats_send > 1:
            stats_copy = copy.deepcopy(self.dbg_stats)
            stats_copy.update({'update_time':now})
            self.send_msg_to_mon({'iface_chassis_stats':stats_copy})
            self.last_stats_send = now

    def send_loop(self):
        self.log.debug("CHA send loop start")
        try:
            tx_sock = RawSocket(self.eth, 0xEEF9)
        except Exception as e:
            self.log.critical(f'Cannot open RAW EHT RECV socket:{repr(e)}')
            return
        tx_sock.sock.settimeout(0.01)

        while True:
            now = time.monotonic()
            self.handshaker(now)
            self.stats_sender(now)
            
            try: msg = self._queue.get(timeout=1)
            except queue.Empty: continue

            if isinstance(msg, str):
                if msg == 'shutdown': break

            elif isinstance(msg, CHA_REQUEST):
                #try: 
                msg_bytes = bytes(msg)
                #except Exception as e:
                #    self.dbg_stats['serialize_errors'] += 1
                #    self.log.error(f'Serialize exception:\n\t{msg.hdr}\n\t{repr(e)}')
                #    continue

                try: 
                    #self.log.debug(f'SEND:{msg.hdr}')
                    tx_sock.send(msg_bytes, dest=self.chassis_mac)
                    self.dbg_stats['tx_ctr'] += 1
                except: self.dbg_stats['tx_sock_exceptions'] += 1
                time.sleep(0.001)

            else: raise RuntimeError('Unexpected msg type in CHA send')

        self.shutdown = True
        self.log.debug("Send loop exit")

    def un_serialize(self, hdr:CHA_PROTO_HDR, payload_bytes):
            retval = None
        #try: 
            if hdr.msg_type is CHA_MSG_TYPE.STREAM_DATA:
                if hdr.nak_code is CHA_NAK_CODE.NO_ERROR:
                    retval = STREAM_DATA_RESPONSE(hdr, payload_bytes)
                else:
                    self.log.debug(f'ERR_RECV:{hdr}')

            elif hdr.msg_type is CHA_MSG_TYPE.STREAM_START_ACK:
                retval = STREAM_START_RESPONSE(hdr)

            elif hdr.msg_type is CHA_MSG_TYPE.STREAM_STOP_ACK:
                retval = STREAM_STOP_RESPONSE(hdr)

            elif hdr.msg_type is CHA_MSG_TYPE.CNTL_STAT_ACK:
                retval = CHA_STATE_RESPONSE(hdr, payload_bytes)

            elif hdr.msg_type is CHA_MSG_TYPE.SRM_STAT_ACK:
                if hdr.nak_code is CHA_NAK_CODE.NO_ERROR:
                    retval = CHA_SRM_STATUS_RESPONSE(hdr, payload_bytes)
                else:
                    self.log.debug(f'RECV:{hdr}')

            elif hdr.msg_type is CHA_MSG_TYPE.CNTL_NODES_BC_ACK:
                if hdr.nak_code is CHA_NAK_CODE.NO_ERROR:
                    retval = CHA_DISCOVERY_RESPONSE(hdr, payload_bytes)
                else:
                    self.log.debug(f'RECV:{hdr}')

            elif hdr.msg_type is CHA_MSG_TYPE.SRM_RUN_ACK:
                if hdr.nak_code is CHA_NAK_CODE.NO_ERROR:
                    retval = CHA_RESPONSE(hdr)
                else:
                    self.log.debug(f'RECV:{hdr}')

            elif hdr.msg_type is CHA_MSG_TYPE.CNTL_CLK_SET_ACK:
                retval = CHA_SET_CLOCK_RESPONSE(hdr, payload_bytes)

            elif hdr.msg_type is  CHA_MSG_TYPE.SRM_FAT_ACK:
                retval = CHA_SRM_TABLE_RESPONSE(hdr, payload_bytes)

            else:
                retval = CHA_RESPONSE(hdr)
                self.log.debug(f'RECV:{hdr}')
        #except Exception as e:
        #    self.dbg_stats['un_serialize_errors'] += 1
        #    self.log.error(f"UN-Serialize {hdr.msg_type.name} exception :\n\t{repr(e)}")
        #    retval = None
            return retval

    def recv_loop(self):
        self.log.debug("CHA recv loop start")
        try:
            rx_sock = RawSocket(self.eth, 0xEEFA)
        except Exception as e:
            self.log.critical(f'Cannot open RAW EHT RECV socket:{repr(e)}')
            return
        
        rx_sock.sock.settimeout(0.25)
        HDR_SZ = CHA_PROTO_HDR.HDR_SZ
        packet_waiting_next_chunk = None
        
        while not self.shutdown:
            try: packet_bytes = rx_sock.recv().data
            except TimeoutError: continue
            except Exception as e:
                self.log.error("RX socket exception:\b\t%s"%repr(e))

            self.dbg_stats['rx_ctr'] += 1
            self.last_rx_activity = time.monotonic()
            hdr = CHA_PROTO_HDR.from_bytes(packet_bytes[:HDR_SZ])
            #self.log.debug(f'RECV:{hdr}')

            payload_sz = len(packet_bytes) - HDR_SZ
            if payload_sz < hdr.chunk_sz:
                self.log.debug(f'RECV:{hdr} Payload size mismatch {payload_sz}/{hdr.chunk_sz}')
                self.dbg_stats['inpt_hdr_errors'] += 1
                continue
            elif payload_sz > hdr.chunk_sz:
                self.dbg_stats['extra_bytes_recvd'] += 1

            payload_bytes = packet_bytes[HDR_SZ:HDR_SZ+hdr.chunk_sz]

            if hdr.if_type is CHA_LR_IF_TYPE.DRIVER:
                if not self.chassis_connected:
                    self.log.warning("Chassis connected")
                    self.chassis_connected = True
                self.dbg_stats['if_type_drived_recvs'] += 1
                continue

            if not (packet := self.un_serialize(hdr, payload_bytes)):
                continue

            if packet.hdr.wait_next_chunk: 
                if packet_waiting_next_chunk:
                    self.log.warning("Chunk sequence error #1")
                    self.dbg_stats['chunk_sequence_error'] += 1
                packet_waiting_next_chunk = packet
                continue

            if packet.hdr.chunk_n:
                if not packet_waiting_next_chunk:
                    self.log.warning("Chunk sequence error #2")
                    self.dbg_stats['chunk_sequence_error'] += 1
                    continue
                else: 
                    packet_waiting_next_chunk.concat_payloads(packet)
                    packet = packet_waiting_next_chunk
                    packet_waiting_next_chunk = None

            if (int(packet.hdr.msg_type)&int(CHA_MSG_TYPE.STR_BIT)) != 0: # stream bit set
                self.send_msg_to_streamproc(packet)
            else: self.send_msg_to_core(packet)

        self.log.debug("Recv loop exit")

