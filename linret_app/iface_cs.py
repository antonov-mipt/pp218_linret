import asyncio, logging, threading, time, copy
from config import PROGRAM_CONFIG
from protocol.cha_enums import *
from protocol.cs_enums import *
from protocol.cha_structs import *
from protocol.cs_structs import *
from protocol.cha_stream_structs import *

class IFACE_TO_CS:
    def __init__(self, program_params:PROGRAM_CONFIG):
        self.log = logging.getLogger('CS')
        self.port = program_params.get_cs_port()
        self.t =threading.Thread(target=self.main_loop, args=[])
        self.run = lambda: self.t.start()
        self.join = lambda: self.t.join()
        self._queue = None
        self.stop_event = None
        self.loop = None
        self.n_clients = 0
        self.shutdown = False
        self.dbg_stats = {
            'tx_ctr': 0,
            'rx_ctr': 0,
            'packets_to_core_dropped_q_full': 0,
            'packets_to_cs_dropped_q_full': 0,
            'packets_to_cs_dropped_no_client': 0,
            'n_reconnections': 0,
            'inpt_hdr_errors': 0,
            'serialize_errors': 0,
            'un_serialize_errors': 0,
        }

    def register_msg_handlers(self, to_core, to_mon):
        self.send_msg_to_core = to_core
        self.send_msg_to_mon = to_mon

    def send_msg_to_cs(self, msg):
        if isinstance(msg, str) and msg == 'shutdown': 
            if self.loop != None and self.stop_event != None:
                self.loop.call_soon_threadsafe(self.stop_event.set)

        if self.n_clients == 0:
            self.dbg_stats['packets_to_cs_dropped_no_client'] += 1
        elif self._queue != None:
            try: 
                self.loop.call_soon_threadsafe(self._queue.put_nowait, msg)
            except asyncio.QueueFull: 
                self.dbg_stats['packets_to_cs_dropped_q_full'] += 1

    def un_serialize(self, hdr:CS_PROTO_HDR, payload_bytes):
        #print("FROM CS", hdr.cs_cmd_type.name)

        if hdr.cs_cmd_type is CS_PACKET_TYPE.NODE_ID_LIST_REQUEST:
            pack = CS_NODE_ID_LIST_REQUEST(hdr, payload_bytes)
            #self.log.debug(pack)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.CHA_LR_STATE_REQUEST:
            pack = CS_REQUEST(hdr, payload_bytes)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.CHA_STATE_REQUEST:
            pack = CS_REQUEST(hdr, payload_bytes)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.SRM_STATE_REQUEST:
            pack = CS_REQUEST(hdr, payload_bytes)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.LR_STATE_REQUEST:
            pack = CS_REQUEST(hdr, payload_bytes)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.CMD_SET_CONFIG:
            pack = CS_ADC_CFG_SET_REQUEST(hdr, payload_bytes)
        elif hdr.cs_cmd_type is CS_PACKET_TYPE.CMD_ACQUISITION_CTL:
            pack = CS_CMD_ACQ_CONTROL_REQUEST(hdr, payload_bytes)
        else: 
            pack = None

        return pack
        #except Exception as e:
        #    self.dbg_stats['un_serialize_errors'] += 1
        #    self.log.error("UN-Serialize exception:\n\t%s"%repr(e))
        #    return None

    async def read_from_socket(self, reader):
        while not self.stop_event.is_set():
            try:
                hdr_bytes = await reader.readexactly(CS_PROTO_HDR.CS_PROTO_HDR_SZ)
            except asyncio.IncompleteReadError: 
                self.log.error('asyncio.IncompleteReadError')
                break
            if not hdr_bytes: break
            else: self.dbg_stats['rx_ctr'] += 1

            try: hdr = CS_PROTO_HDR(hdr_bytes)
            except Exception as e: 
                self.log.debug(f"Parse CS HDR exception:\n\t{repr(e)}")
                self.dbg_stats['inpt_hdr_errors'] += 1
                continue

            SN_EMULATOR(CS_SN=hdr.src_serial_bytes) # register CS serial

            if hdr.payload_length: 
                try: payload_bytes = await reader.readexactly(hdr.payload_length)
                except asyncio.IncompleteReadError: break
                if not payload_bytes: break
            else: payload_bytes = b''

            packet = self.un_serialize(hdr, payload_bytes)
            if packet != None: self.send_msg_to_core(packet)

    async def write_to_socket(self, writer:asyncio.StreamWriter):
        while True:
            if self.stop_event.is_set(): break
            if self._queue is None: 
                self.log.error("Queue is None")
                await asyncio.sleep(0.5)
                break
            #if writer.: break
            try: msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError: continue
            #self.log.info(f"TO CS: {msg.hdr.cs_cmd_type.name}")
            if isinstance(msg, str) and msg == 'shutdown': break
            elif isinstance(msg, CS_RESPONSE):
                #try: 
                msg_bytes = bytes(msg)
                #except Exception as e:
                #    self.dbg_stats['serialize_errors'] += 1
                #    self.log.error("Serialize exception:\n\t%s"%repr(e))
                #    msg_bytes = None
                if msg_bytes:
                    self.dbg_stats['tx_ctr'] += 1
                    #print("W: %s"%msg_bytes.hex())
                    try:
                        writer.write(msg_bytes)
                        await writer.drain()
                    except ConnectionResetError:
                        self.log.warning("Connection reset")
                        break
        writer.close()

    async def socket_client_task(self, reader, writer):
        #if self.n_clients > 0:
        #    self.log.warning("New client trying to connect while old is still connected")
        #    writer.close()
        #else:
            try: 
                if self.n_clients == 0: self._queue = asyncio.Queue()
                self.n_clients += 1
                self.log.warning("CS %u connected"%self.n_clients)
                self.dbg_stats['n_reconnections'] += 1
                self.loop.create_task(self.write_to_socket(writer))
                await self.read_from_socket(reader)
                self.log.warning("CS %u disconnected"%self.n_clients)
                writer.close()
                
            #except asyncio.CancelledError: 
            #    pass
            except Exception as e: 
                self.log.error('socket_client_task exception:\n\t%s'%repr(e))
            finally: 
                self.n_clients -= 1
                if self.n_clients == 0: self._queue = None
                self.log.debug('socket_client_task stopped')
            #self.closed.set()

    async def socket_server_task(self):
        try: 
            await self.socket_server_loop()
        except asyncio.CancelledError: pass
        except Exception as e: 
            self.log.error('socket_server_task exception:\n\t%s'%repr(e))
        finally: 
            self.log.debug('socket_server_task stopped')
            #self.closed.set()

    async def socket_server_loop(self):
        handler = lambda r, w: self.socket_client_task(r, w)
        server = await asyncio.start_server(handler, '', self.port, reuse_address = True)
        async with server: 
            while not self.stop_event.is_set():
                now = time.monotonic()
                stats_copy = copy.deepcopy(self.dbg_stats)
                stats_copy.update({'update_time':now})
                self.send_msg_to_mon({'iface_cs_stats':stats_copy})
                try: await asyncio.wait_for(self.stop_event.wait(), timeout=1)
                except TimeoutError: pass

    def main_loop(self):
        self.log.debug('CS loop start')
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()
        self.loop.run_until_complete(self.socket_server_loop())
        self.log.debug('CS loop stop')
        