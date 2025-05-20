import queue, logging, threading, time, copy, collections, enum
import bson
import pymongo, pymongo.errors
from nmea_true_time import TRUE_TIME
from config import PROGRAM_CONFIG
from protocol.cha_enums import *
from protocol.cs_enums import *
from protocol.cha_structs import *
from protocol.cs_structs import *
from protocol.cha_stream_structs import *

class JOB_GLOBAL_STATE(enum.Enum):
    INACTIVE = enum.auto()
    ACTIVE = enum.auto()
    FINISHED = enum.auto()

class JOB_IFACE_STATE(enum.Enum):
    INACTIVE = enum.auto()
    WAIT_START_ACK = enum.auto()
    WAIT_DATA = enum.auto()
    WAIT_STOP_ACK = enum.auto()
    FINISHED = enum.auto()

class STREAM_INTERFACE_JOB:
    WAIT_START_TIMEOUT_MS = 200
    WAIT_STOP_TIMEOUT_MS = 100
    WAIT_DATA_TIMEOUT_MS = 1500
    rand_id_ctr = 0

    def packet_n(self, node_id, packet_in_node):
        return (self.ppn*(node_id-1)) + packet_in_node

    def stream_rand_id(self):
        retval = STREAM_INTERFACE_JOB.rand_id_ctr
        STREAM_INTERFACE_JOB.rand_id_ctr += 1
        if STREAM_INTERFACE_JOB.rand_id_ctr == 256:
            STREAM_INTERFACE_JOB.rand_id_ctr = 0
        return retval

    def __init__(self,
                 iface:CHA_LR_IF_TYPE, 
                 adc_params:UNI_ADC_CFG,
                 send_to_chassis,
                 timestamp, 
                 devs_list
                 ):
        
        self.log = logging.getLogger('JOB')
        self.ppn = adc_params.packets_per_node()
        self.name = f'{timestamp}_{iface.name}'
        #self.debug = lambda msg: self.log.debug(f'[{self.name}] {msg}')
        #self.warning = lambda msg: self.log.debug(f'[{self.name}] {msg}')
        self.debug = lambda msg: None
        self.warning = lambda msg: None
        self.adc_params = adc_params
        self.iface = iface
        self.rand_id = self.stream_rand_id()
        self.timestamp = timestamp
        self.job_packet_numbers = list()
        self.node_ids = list()
        self.node_id_to_srm_sn = dict()
        for dev in devs_list:
            self.node_ids.append(dev['addr'])
            self.node_id_to_srm_sn.update({dev['addr']:dev['srm_serial_bytes']})
        for node_id in self.node_ids:
            for n in range(self.ppn): 
                packet_n = self.packet_n(node_id, n)
                self.job_packet_numbers.append(packet_n)
        self.recvd_packet_numbers = list()
        self.state = JOB_IFACE_STATE.INACTIVE
        self.debug(f'{iface.name}:{len(self.job_packet_numbers)} packets')

        self.send_start = lambda p: send_to_chassis(STREAM_START_REQUEST(
            self.iface, self.rand_id, self.timestamp, p, self.adc_params.code))
        self.send_feedback = lambda p: send_to_chassis(STREAM_FEEDBACK_REQUEST(
            self.iface, self.rand_id, self.timestamp, p))
        self.send_stop = lambda: send_to_chassis(STREAM_STOP_REQUEST(
            self.iface, self.rand_id))
        
        self.start_ack_start_time = None
        self.start_wait_time = 0
        self.data_recv_start_time = None
        self.data_wait_time = 0
        self.stop_ack_start_time = None
        self.stop_wait_time = 0
        self.start_ack_recvd = False
        self.data_recvd = False
        self.stop_ack_recvd = False
        self.db_write_time = None
        self.db_index_time = 0
        self.stored_data = dict()
        self.joined_data = dict()

        self.data_to_db = list()
        self.time_to_db = list()
        self.db = None
        self.data_collection = None
        self.time_cache_collection = None

        self.bson_time_start = bson.Int64(self.timestamp*1000000000)

    def append_db(self, db, db_config):
        self.db = db
        self.data_collection = self.db[db_config['data_collection']]
        self.time_cache_collection = self.db[db_config['timecache_collection']]
        
    def work(self, now):
        if self.state is JOB_IFACE_STATE.INACTIVE:
            self.start_ack_start_time = now
            self.state = JOB_IFACE_STATE.WAIT_START_ACK
            self.debug('Job started')

        if self.state is JOB_IFACE_STATE.WAIT_START_ACK:
            self.start_wait_time = int((now - self.start_ack_start_time)*1000)
            if self.start_ack_recvd:
                self.state = JOB_IFACE_STATE.WAIT_DATA
                self.debug(f'Start ack`ed in {self.start_wait_time}ms')
                self.data_recv_start_time = now
            elif self.start_wait_time > STREAM_INTERFACE_JOB.WAIT_START_TIMEOUT_MS:
                self.warning(f'Wait start ACK timeout')
                self.state = JOB_IFACE_STATE.WAIT_STOP_ACK
                self.stop_ack_start_time = now
            else:
                self.send_start(self.job_packet_numbers)

        if self.state is JOB_IFACE_STATE.WAIT_DATA:
            self.data_wait_time = int((now - self.data_recv_start_time)*1000)
            if set(self.job_packet_numbers) == set(self.recvd_packet_numbers):
                self.data_recvd = True
                self.state = JOB_IFACE_STATE.WAIT_STOP_ACK
                self.debug(f'Data recvd in {self.data_wait_time}ms')
                self.stop_ack_start_time = now
            elif self.data_wait_time > STREAM_INTERFACE_JOB.WAIT_DATA_TIMEOUT_MS:
                self.warning(f'Data wait timeout')
                self.state = JOB_IFACE_STATE.WAIT_STOP_ACK
                self.stop_ack_start_time = now
            else:
                self.send_feedback(self.recvd_packet_numbers)

        if self.state is JOB_IFACE_STATE.WAIT_STOP_ACK:
            self.stop_wait_time = int((now - self.stop_ack_start_time)*1000)
            if self.stop_ack_recvd:
                self.state = JOB_IFACE_STATE.FINISHED
                self.debug(f'Stop ack`ed in {self.stop_wait_time}ms')
            elif self.stop_wait_time > STREAM_INTERFACE_JOB.WAIT_STOP_TIMEOUT_MS:
                self.warning(f'Wait stop ACK timeout')
                self.state = JOB_IFACE_STATE.FINISHED
            else:
                self.send_stop()

        if self.state is JOB_IFACE_STATE.FINISHED:
            if self.data_to_db and (self.data_collection is not None):
                try:
                    db_write_start = time.monotonic()
                    self.data_collection.insert_many(self.data_to_db)
                    self.db_write_time = int((time.monotonic() - db_write_start)*1000)
                except Exception as e:
                    self.log.warning(f'DB insert_many exception {repr(e)}')
                self.data_to_db = None

            if self.time_to_db and (self.data_collection is not None):
                start = time.monotonic() 
                for int_mac in self.time_to_db:
                    try:
                        self.time_cache_collection.update_one(
                            {"serial": int_mac}, 
                            {"$max": { "time_start": self.bson_time_start}}, 
                            upsert=True)
                    except Exception as e:
                        self.log.warning(f'DB update_one exception {repr(e)}')
                self.db_index_time += int((time.monotonic() - start)*1000)
                self.time_to_db = None

    
    def store_data(self, packet:STREAM_DATA_RESPONSE):
        sn = self.node_id_to_srm_sn[packet.node_id]
        #print(sn)
        if sn not in self.stored_data: self.stored_data.update({sn:dict()})
        if packet.packet_n not in self.stored_data[sn]:
            self.stored_data[sn].update({packet.packet_n:packet.payload})
            if len(self.stored_data[sn]) == self.ppn:
                data = [self.stored_data[sn][i] for i in range(self.ppn)]
                result = b''.join(data)
                self.joined_data.update({sn.decode():result})
                if self.db is not None:
                    int_mac = bson.Int64(int.from_bytes(sn, byteorder='little'))

                    post = {
                        "serial": int_mac,
                        "time_start": self.bson_time_start,
                        "time_diff": bson.Int64(0),
                        "time_diff_measurement_time": bson.Int64(0),
                        "samples_count": self.adc_params.datarate_value(),
                        "frequency": CS_ADC_DR_CODE[self.adc_params.adc_datarate.name],
                        "channels": self.adc_params.ch_bit_mask,
                        "gain": self.adc_params.gain_bit_mask,
                        "data": result
                    }

                    #post_time = (
                    #    {"serial": int_mac},
                    #    {"$max": {"time_start": self.bson_time_start}}
                    #)

                    self.data_to_db.append(post)
                    self.time_to_db.append(int_mac)

                    #try:
                    #    start = time.monotonic()
                    #    self.time_cache_collection.update_one(
                    #        {"serial": int_mac}, 
                    #        {"$max": {
                    #            "time_start": self.bson_time_start
                    #            }
                    #        }
                    #        , upsert=True)
                    #    self.db_index_time += int((time.monotonic() - start)*1000)
                    #except Exception as e:
                    #    self.log.warning(f'DB update_one exception {repr(e)}')

                
                #self.log.info(f'[{self.timestamp}] [{sn}] recvd {len(result)} bytes')
                #with open(f'/home/ntcmg/tmp/{self.name}_{packet.node_id:2d}.dat', 'wb') as f:
                #    f.write(result)

    def process_data_packet(self, packet:STREAM_DATA_RESPONSE):
        packet_n = self.packet_n(packet.node_id, packet.packet_n)
        if packet_n not in self.recvd_packet_numbers:
            self.recvd_packet_numbers.append(packet_n)
        if set(self.job_packet_numbers) == set(self.recvd_packet_numbers):
            self.data_recvd = True
            self.send_stop()
        if packet.payload_present: self.store_data(packet)
        else: self.log.error(f'Empty packet {packet.node_id}:{packet.packet_n}')
    
    def rx_packet(self, packet:CHA_RESPONSE):

        if self.state is JOB_IFACE_STATE.WAIT_START_ACK:
            if isinstance(packet, (STREAM_START_RESPONSE, STREAM_DATA_RESPONSE)):
                if not self.start_ack_recvd: self.start_ack_recvd = True
                if isinstance(packet, STREAM_DATA_RESPONSE):
                    if not self.data_recvd: self.process_data_packet(packet)
            else: # STREAM_STOP_RESPONSE
                self.debug(f'Unexpected {packet.hdr.msg_type.name} recvd')

        elif self.state is JOB_IFACE_STATE.WAIT_DATA:
            if isinstance(packet, STREAM_DATA_RESPONSE):
                if not self.data_recvd: self.process_data_packet(packet)
            else:
                self.debug(f'Unexpected {packet.hdr.msg_type.name} recvd')

        elif self.state is JOB_IFACE_STATE.WAIT_STOP_ACK:
            if isinstance(packet, STREAM_STOP_RESPONSE):
                if not self.stop_ack_recvd: self.stop_ack_recvd = True
            elif isinstance(packet, STREAM_DATA_RESPONSE):
                if not self.data_recvd: self.process_data_packet(packet)
            else:
                self.debug(f'Unexpected {packet.hdr.msg_type.name} recvd')

    STATS_HDR = [{'txt':'0_TIME'},{'txt':'IFACE'},
                 {'txt':'RATE'},{'txt':'N'},
                 {'txt':'RECV_PACKS'},
                 {'txt':'START'},{'txt':'RECV'},{'txt':'STOP'},
                 {'txt':'DB IDX'}, {'txt':'DB_DATA'}
                 ]
    
    def generate_stats(self):
        #req_packs = struct.pack('>L', *self.job_packet_numbers[:1]).hex()
        mask = [0]*4
        for i in range(len(mask)):
            for j in range(32):
                if (i*32+j) in self.recvd_packet_numbers:
                    mask[i] |= 1<<j

        recv_packs = struct.pack('<4L', *mask).hex().upper()
        #recv_packs = len(self.recvd_packet_numbers)
        color = 'green' if (set(self.job_packet_numbers)==set(self.recvd_packet_numbers)) else 'red'

        def lat(success, time, timeout):
            if not success: return {'txt':'---', 'color':'red'}
            elif time > (0.5*timeout): return {'txt':f'{time}ms', 'color':'orange'}
            else: return {'txt':f'{time}ms', 'color':'green'}

        return[
            {'txt':str(self.timestamp)}, {'txt':str(self.iface.name)}, 
            {'txt':str(self.adc_params.datarate_value())}, {'txt':len(self.node_ids)}, 
            {'txt':recv_packs,'color':color},
            lat(self.start_ack_recvd, self.start_wait_time, STREAM_INTERFACE_JOB.WAIT_START_TIMEOUT_MS),
            lat(self.data_recvd, self.data_wait_time, STREAM_INTERFACE_JOB.WAIT_DATA_TIMEOUT_MS),
            lat(self.stop_ack_recvd, self.stop_wait_time, STREAM_INTERFACE_JOB.WAIT_STOP_TIMEOUT_MS),
            {'txt':f'{str(self.db_index_time)}ms'}, {'txt':f'{str(self.db_write_time)}ms'}
        ]

class STREAM_JOB:
    def __init__(self, send_to_chassis, send_to_mon, timestamp:int,  adc_params:UNI_ADC_CFG, \
                 active_devs:dict[CHA_LR_IF_TYPE:list]):
        self.log = logging.getLogger('JOB')
        self.timestamp = timestamp
        #self.log.debug(f'[{self.timestamp}] Job scheduled')
        self.adc_params = adc_params
        self.state = JOB_GLOBAL_STATE.INACTIVE
        self.send_to_mon = send_to_mon
        self.data_sent_to_mon = False

        self.iface_jobs = dict()
        for iface, devs_list in active_devs.items():
            self.iface_jobs.update({iface:STREAM_INTERFACE_JOB(
                    iface, adc_params, send_to_chassis, timestamp, devs_list
            )})

    def append_db(self, db, db_config):
        for job in self.iface_jobs.values():
            job.append_db(db, db_config)

    def work(self, now):
        if self.state is JOB_GLOBAL_STATE.INACTIVE:
            #self.log.info(f'[{self.timestamp}] Job started')
            self.state = JOB_GLOBAL_STATE.ACTIVE
        
        if self.state is JOB_GLOBAL_STATE.ACTIVE:
            ifaces_finished = True
            for iface, job in self.iface_jobs.items(): 
                job.work(now)
                if job.state is not JOB_IFACE_STATE.FINISHED: 
                    ifaces_finished = False
            if ifaces_finished: self.state = JOB_GLOBAL_STATE.FINISHED

        if self.state is JOB_GLOBAL_STATE.FINISHED:
            #self.log.info(f'[{self.timestamp}] Job finished')
            if not self.data_sent_to_mon:
                msg = {
                    'timestamp': self.timestamp, 
                    'adc_params': self.adc_params,
                    'nodes_raw_bytes':dict()
                    }
                for iface_job in self.iface_jobs.values():
                    msg['nodes_raw_bytes'].update(iface_job.joined_data)
                self.send_to_mon({'job_data': msg})
                self.data_sent_to_mon = True

        return self.state

    def rx_packet(self, packet:CHA_RESPONSE):
        if packet.hdr.if_type in self.iface_jobs:
            self.iface_jobs[packet.hdr.if_type].rx_packet(packet)
    
    def generate_stats(self):
        return [job.generate_stats() for job in self.iface_jobs.values()]

class LINRET_STREAMREADER:
    JOB_CALL_MIN_INTERVAL = 0.015 # 15 ms

    def __init__(self, pc:PROGRAM_CONFIG, true_time:TRUE_TIME):
        self.true_time = true_time
        self.program_config = pc
        self.db_config = pc.get_db_config()
        self.log = logging.getLogger('STREAM')
        self._queue = queue.Queue(maxsize=25)
        self.t = threading.Thread(target=self.stream_loop, args=[])
        self.run = lambda: self.t.start()
        self.join = lambda: self.t.join()
        self.last_job_call_time = 0
        self.last_stats_send = 0
        self.last_ty_db_connect = 0
        self.jobs_queue = collections.deque([], maxlen=5)
        self.jobs_stats = collections.deque([], maxlen=20)
        self.active_job:STREAM_JOB = None
        self.last_tx_time = 0
        self.last_job_finish_time = 0
        self.delay_between_requests = pc.get_delay_between_requests()
        self.delay_before_request = pc.get_delay_before_request()

        self.db_client = pymongo.MongoClient(self.db_config['url'])
        self.db = self.db_client[self.db_config['db_name']]
        self.db_connected = False
        
        self.dbg_stats = {
            'queue_full_drops': 0,
            'invalid_packets_drops': 0,
            'stream_rx_while_no_job': 0,
            'job_queue_len': 0
        }

    def try_connect_to_db(self, now):
        if now - self.last_ty_db_connect > 5:
            self.last_ty_db_connect = now
            try:
                self.db_client.admin.command('ping')
                if not self.db_connected:
                    collection = self.db[self.db_config['data_collection']]
                    time_cache_collection = self.db[self.db_config['timecache_collection']]
                    indexes = collection.list_indexes()
                    indexes = [index['name'] for index in indexes]
                    if 'serial_1' not in indexes:
                        collection.create_index([("serial", 1)], unique=False)
                    if 'time_start_1' not in indexes:
                        collection.create_index([("time_start", 1)], unique=False)
                    if 'serial_1_time_start_1' not in indexes:
                        collection.create_index([("serial", 1), ("time_start", 1)], unique=True)
                    indexes = time_cache_collection.list_indexes()
                    indexes = [index['name'] for index in indexes]
                    if 'serial_1' not in indexes:
                        time_cache_collection.create_index([("serial", 1)], unique=False)
                    if 'time_start_1' not in indexes:
                        time_cache_collection.create_index([("time_start", 1)], unique=False)
                    if 'serial_1_time_start_1' not in indexes:
                        time_cache_collection.create_index([("serial", 1), ("time_start", 1)], unique=True)
                    self.log.warning(f'Connected to DB {self.db_config["url"]}')
                self.db_connected = True
            except pymongo.errors.ConnectionFailure:
                self.log.error("Connection to DB error")
                if self.db_connected: self.log.error("Connection to DB lost")
                self.db_connected = False

    def register_msg_handlres(self, to_cha, to_core, to_mon):
        self.send_to_chassis = to_cha
        self.send_to_mon = to_mon
        self.send_to_core = to_core

    def stats_sender(self, now):
        if now - self.last_stats_send > 1:
            jobs_stats = [STREAM_INTERFACE_JOB.STATS_HDR] + list(self.jobs_stats)

            stats = {
                'streamer_stats': copy.deepcopy(self.dbg_stats),
                'jobs_stats': jobs_stats
                }
            stats['job_queue_len'] = len(self.jobs_queue)
            self.send_to_mon(stats)
            self.last_stats_send = now

    def send_msg_to_streamer(self, msg):
        try: self._queue.put_nowait(msg)
        except queue.Full: self.dbg_stats['queue_full_drops'] += 1

    def job_scheduler(self, now):
        #print("1")
        if (now - self.last_job_call_time) < LINRET_STREAMREADER.JOB_CALL_MIN_INTERVAL:
            return
        else: self.last_job_call_time = now
        
        if self.active_job:
            if self.active_job.work(now) is JOB_GLOBAL_STATE.FINISHED:
                self.jobs_stats.extend(self.active_job.generate_stats())
                self.active_job = None
                self.send_to_core('job_finished')

        delay_ok = (now > (self.last_job_finish_time + self.delay_between_requests))
        if (not self.active_job) and self.jobs_queue and delay_ok:
            abs_time = self.true_time.get_true_time()
            #print("CCC")
            if abs_time is not None:
                if (abs_time - self.jobs_queue[0].timestamp) > self.delay_before_request:
                    self.active_job = self.jobs_queue.popleft()
                    self.log.debug(f'{self.active_job.timestamp}:{abs_time - self.active_job.timestamp}')
                    #if self.db_connected: 
                    self.active_job.append_db(self.db, self.db_config)
                    self.active_job.work(now)
                    self.send_to_core('job_active')

    def stream_loop(self):
        self.log.debug('Streamer loop start')

        while True:
            now = time.monotonic()
            #self.try_connect_to_db(now)
            self.stats_sender(now)
            self.job_scheduler(now)

            try: msg = self._queue.get(timeout=0.025)
            except queue.Empty: continue

            if isinstance(msg, str) and msg == 'shutdown': 
                break

            elif isinstance(msg, CHA_RESPONSE): 
                if self.active_job: 
                    self.active_job.rx_packet(msg)
                else: self.dbg_stats['stream_rx_while_no_job'] += 1

            elif isinstance(msg, STREAM_JOB): 
                self.jobs_queue.append(msg)

            else: self.dbg_stats['invalid_packets_drops'] += 1

        if self.db_client: self.db_client.close()
        self.log.debug('Streamer loop finish')

    def tx_traffic_shaper(self, packet):
        now = time.monotonic()
        if now - self.last_tx_time > LINRET_STREAMREADER.TX_MIN_INTERVAL:
            self.send_to_chassis(packet)
            self.last_tx_time = now

