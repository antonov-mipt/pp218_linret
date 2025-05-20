from __future__ import annotations
import struct, time
from .uni_structs import *
from .cha_enums import *
from .helpers import *

CHA_PARAMS_SN_SZ = 8

'''
CHA-LR HEADER
'''

class CHA_PROTO_HDR:
    CHA_HDR_DATASTRUCT = '<BBH 4x BxxxBBBB'
    HDR_SZ = struct.calcsize(CHA_HDR_DATASTRUCT)

    def __init__(self, iface:CHA_LR_IF_TYPE, msg:CHA_MSG_TYPE,
                 chu:int=0, sz:int=0, rand:int=0, 
                 src:int=0, dst:int=1, 
                 nak:CHA_NAK_CODE=CHA_NAK_CODE.NO_ERROR
                 ):
        self.if_type, self.src_addr, self.dst_addr = iface, src, dst
        self.msg_type, self.nak_code = msg, nak
        self.random_id, self.chunk_n, self.chunk_sz = rand, chu, sz
        self.wait_next_chunk = False

    @classmethod
    def from_bytes(cls, inpt:bytes) -> CHA_PROTO_HDR:
        tupl = struct.unpack(cls.CHA_HDR_DATASTRUCT, inpt)
        return cls(CHA_LR_IF_TYPE(tupl[0]), CHA_MSG_TYPE(tupl[6]),
                   chu=tupl[1], sz=tupl[2], rand=tupl[3], 
                   src=tupl[4], dst=tupl[5], nak=CHA_NAK_CODE(tupl[7])
        )

    def __bytes__(self):
        return struct.pack(CHA_PROTO_HDR.CHA_HDR_DATASTRUCT, 
            self.if_type, self.chunk_n, self.chunk_sz,
            self.random_id, self.src_addr, self.dst_addr,
            self.msg_type, self.nak_code
        )
    
    def __str__(self):
        nak = 'OK' if self.nak_code is CHA_NAK_CODE.NO_ERROR else self.nak_code.name
        return f'{self.if_type.name}:{self.src_addr}>{self.dst_addr}:{self.chunk_n}/{self.chunk_sz}:{self.msg_type.name}:{nak}'
    
'''
REQUESTS TO CHASSIS/SRM
'''
class CHA_REQUEST:
    def __init__(self, hdr:CHA_PROTO_HDR):
        self.hdr = hdr
        self.send_time = time.monotonic()

    def validate_response(self, response:CHA_RESPONSE):
        return self.hdr.if_type is response.hdr.if_type and \
                self.hdr.dst_addr == response.hdr.src_addr and \
                self.hdr.random_id == response.hdr.random_id
    
    def __bytes__(self):
        return bytes(self.hdr)   
    
    def __str__(self):
        return f'{self.hdr.msg_type.name} to {self.hdr.if_type.name}:{self.hdr.dst_addr}'
    
class CHA_HANDSHAKE_REQUEST(CHA_REQUEST):
    def __init__(self):
        hdr = CHA_PROTO_HDR(CHA_LR_IF_TYPE.DRIVER, CHA_MSG_TYPE.LR_HANDSHAKE_REQ)
        super().__init__(hdr)
    
class CHA_SIMPLE_REQUEST(CHA_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, msg_type:CHA_MSG_TYPE, dst, rand):
        hdr = CHA_PROTO_HDR(iface, msg_type, dst=dst, rand=rand)
        super().__init__(hdr)
    
class CHA_SRM_STATUS_REQUEST(CHA_SIMPLE_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst, rand):
        super().__init__(iface, CHA_MSG_TYPE.SRM_STAT_REQ, dst, rand)
    
class CHA_STATE_REQUEST(CHA_SIMPLE_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst:int, rand:int):
        super().__init__(iface, CHA_MSG_TYPE.CNTL_STAT_REQ, dst, rand)
    
class CHA_DISCOVERY_REQUEST(CHA_SIMPLE_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst:int, rand:int):
        super().__init__(iface, CHA_MSG_TYPE.CNTL_NODES_BC_REQ, dst, rand)

class CHA_SRM_STOP_REQUEST(CHA_SIMPLE_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst:int, rand:int):
        super().__init__(iface, CHA_MSG_TYPE.SRM_STOP_REQ, dst, rand)

class CHA_SRM_TABLE_REQUEST(CHA_SIMPLE_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst, rand):
        super().__init__(iface, CHA_MSG_TYPE.SRM_FAT_REQ, dst, rand)
    
class CHA_SRM_RUN_REQUEST(CHA_REQUEST):
    SRM_CMD_DATASTRUCT = '<L?xHLL4s'
    CHA_CMD_DATASTRUCT = '<??xx'

    def __init__(self, iface:CHA_LR_IF_TYPE, dst, rand,\
                 adc_params:UNI_ADC_CFG, gps:CHA_GPS_STRUCT):
        hdr = CHA_PROTO_HDR(iface, CHA_MSG_TYPE.SRM_RUN_REQ, dst=dst, rand=rand)
        self.flag_use_chassis_time = True
        if gps.gps_lat != 0 and gps.gps_lon != 0:
            self.flag_use_chassis_coord = True
            self.lat = int(gps.gps_lat*1000000)
            self.lon = int(gps.gps_lon*1000000)
            self.height = gps.gps_height
        else: 
            self.flag_use_chassis_coord = False
            self.lat = 0
            self.lon = 0
            self.height = 0
        self.ignore_pps = False
        self.adc_params = adc_params
        self.cmd_send_time = 0
        super().__init__(hdr)

    def __bytes__(self):
        srm_cmd_bytes = struct.pack(self.SRM_CMD_DATASTRUCT,
            int(self.cmd_send_time),
            self.ignore_pps,
            self.height, self.lat, self.lon, # gps
            self.adc_params.to_srm_bytes()
        )

        cha_cmd_bytes = struct.pack(self.CHA_CMD_DATASTRUCT,
            self.flag_use_chassis_time, self.flag_use_chassis_coord
        )

        self.hdr.chunk_sz = len(cha_cmd_bytes) + len(srm_cmd_bytes)
        return bytes(self.hdr) + cha_cmd_bytes + srm_cmd_bytes
    

    
class CHA_SET_CLOCK_REQUEST(CHA_REQUEST):
    def __init__(self, iface:CHA_LR_IF_TYPE, dst, rand, true_unix_time):
        hdr = CHA_PROTO_HDR(iface, CHA_MSG_TYPE.CNTL_CLK_SET_REQ, dst=dst, rand=rand)
        self.second = int(true_unix_time)
        self.true_unix_time = true_unix_time
        super().__init__(hdr)

    def __bytes__(self):
        payload = struct.pack('<L', self.second)
        self.hdr.chunk_sz = len(payload)
        return bytes(self.hdr) + payload

'''
RESPONSES FROM CHASSIS/SRM
'''
class CHA_RESPONSE:
    def __init__(self, hdr:CHA_PROTO_HDR):
        self.hdr = hdr
        self.recv_time = time.monotonic()

    def __str__(self):
        return f'{self.hdr.msg_type.name} from {self.hdr.if_type.name}:{self.hdr.src_addr}'

class CHA_SET_CLOCK_RESPONSE(CHA_RESPONSE):
    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)
        if payload_bytes: self.phase = struct.unpack('<L', payload_bytes)[0]
        else: self.phase = None

class CHA_SRM_STATUS_RESPONSE(CHA_RESPONSE):
    SRM_DATA_HDR_STRUCT = f'<qqLllhH3h3hHBBL4s'

    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)
        
        tupl = struct.unpack(CHA_SRM_STATUS_RESPONSE.SRM_DATA_HDR_STRUCT, payload_bytes)
        self.samples_timestamp_ns = tupl[0]
        self.pps_timestamp_ns = tupl[1]
        self.unix_timestamp = tupl[2]
        self.latitude = tupl[3]
        self.longitude = tupl[4]
        self.height = tupl[5]
        self.pressure = tupl[6]
        self.acc = [tupl[7], tupl[8], tupl[9]]
        self.mag = [tupl[10], tupl[11], tupl[12]]
        #self.rsrvd_voltage = tupl[13]
        self.temperature = tupl[14]
        self.humidity = tupl[15]
        self.adc_params = UNI_ADC_CFG.from_srm_bytes(tupl[17])

        #flags
        unpacker = bit_unpack(tupl[16])
        next(unpacker)

        self.fatal_error = bool(unpacker.send(1))
        self.pps_present = bool(unpacker.send(1))
        self.vbus_present = bool(unpacker.send(1))
        self.eeprom_consts_ok = bool(unpacker.send(1))
        self.vcxo_pwm_in_range = bool(unpacker.send(1))
        self.adc_sync_ok = bool(unpacker.send(1))
        self.acq_running = bool(unpacker.send(1))
        self.sd_record_running = unpacker.send(1)

        self.test_mode_on = bool(unpacker.send(1))
        self.card_reader_on = bool(unpacker.send(1))
        self.sensor_power_on = bool(unpacker.send(1))
        self.adc_power_on = bool(unpacker.send(1))
        self.rsrvd2 = unpacker.send(4)

        self.adc0_ok = bool(unpacker.send(1))
        self.adc1_ok = bool(unpacker.send(1))
        self.adc2_ok = bool(unpacker.send(1))
        self.adc3_ok = bool(unpacker.send(1))

        self.sd_ok = bool(unpacker.send(1))
        self.acc_ok = bool(unpacker.send(1))
        self.humid_ok = bool(unpacker.send(1))
        self.press_ok = bool(unpacker.send(1))

        self.fw_ver =  unpacker.send(4)
        self.fw_subver =  unpacker.send(4)

class CHA_GPS_STRUCT:
    CHA_GPS_STRUCT = '<llBBhL'
    def __init__(self, payload_bytes):
        tupl = struct.unpack(CHA_GPS_STRUCT.CHA_GPS_STRUCT, payload_bytes)
        self.gps_lon = tupl[0]/10000000
        self.gps_lat = tupl[1]/10000000
        self.fix = tupl[2]
        self.num_sv = tupl[3]
        self.gps_height = tupl[4]
        self.unix_time = tupl[5]
        
class CHA_STATE_RESPONSE(CHA_RESPONSE):
    CHA_PARAMS_COMMENT_SZ = 64
    CHA_PARAMS_STRUCT = f'<{CHA_PARAMS_SN_SZ}s{CHA_PARAMS_COMMENT_SZ}sBBBB??xxBB6sBB6sBBBB'
    PARAMS_SZ = struct.calcsize(CHA_PARAMS_STRUCT)
    CHA_STATE_STRUCT = f'<L16s16s32s12sff{PARAMS_SZ}s6s6s'

    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)

        tupl = struct.unpack(CHA_STATE_RESPONSE.CHA_STATE_STRUCT, payload_bytes)

        #flags
        unpacker = bit_unpack(tupl[0])
        next(unpacker)
        self.sys_wifi_port0_ok = bool(unpacker.send(1))
        self.sys_wifi_port1_ok = bool(unpacker.send(1))
        self.sys_rs485_port0_ok = bool(unpacker.send(1))
        self.sys_rs485_port1_ok = bool(unpacker.send(1))
        self.sys_ethernet_ok = bool(unpacker.send(1))
        self.sys_srm_port_ok = bool(unpacker.send(1))
        self.sys_wifi_link0_ok = bool(unpacker.send(1))
        self.sys_wifi_link1_ok = bool(unpacker.send(1))

        self.hw_pca9536d_ok = bool(unpacker.send(1))
        self.hw_gps_ok = bool(unpacker.send(1))
        self.hw_hts221_ok = bool(unpacker.send(1))
        self.hw_vcxo_ok = bool(unpacker.send(1))
        self.hw_pvc_pwr_ok =  bool(unpacker.send(1))
        self.hw_batt_0_charging =  bool(unpacker.send(1))
        self.hw_batt_1_charging =  bool(unpacker.send(1))
        self.hw_reserved = unpacker.send(1)

        self.mode_lr = bool(unpacker.send(1))
        self.mode_obs = bool(unpacker.send(1))
        self.mode_nodal = bool(unpacker.send(1))
        self.mode_reserved = unpacker.send(5)

        self.state_pps_ok = bool(unpacker.send(1))
        self.state_time_sync_ok = bool(unpacker.send(1))
        self.state_srm_powered = bool(unpacker.send(1))
        self.state_srm_connected = bool(unpacker.send(1))
        self.state_downlink_ok = bool(unpacker.send(1))
        self.state_uplink_ok = bool(unpacker.send(1))
        self.state_srm_active = bool(unpacker.send(1))
        self.state_srm_scheduled = bool(unpacker.send(1))

        # GPS readings
        self.gps = CHA_GPS_STRUCT(tupl[1])
        self.latest_valid_gps = CHA_GPS_STRUCT(tupl[2])

        # ADC readings
        adc_vals = struct.unpack('<8f', tupl[3])
        self.batt_vin = [adc_vals[0], adc_vals[1]]
        self.miniBatt_v = adc_vals[2]
        self.pvc_vin = adc_vals[3]
        self.chassis_pwr = adc_vals[4]
        self.srm_pwr = adc_vals[5]
        self.charge_curr = adc_vals[6]
        self.charge_pwr = adc_vals[7]

        # Time sync state
        datastruct = '<BBBBLL'
        ts_vals = struct.unpack(datastruct, tupl[4])
        self.chasis_time_valid = bool(ts_vals[0])
        self.inpt_pps_valid = bool(ts_vals[1])
        self.pps_mode = ts_vals[2]
        self.vcxo_pwm_in_range = bool(ts_vals[3])
        self.appended_unix_time = ts_vals[4]
        self.curr_time = ts_vals[5]

        # Params
        params = struct.unpack(CHA_STATE_RESPONSE.CHA_PARAMS_STRUCT, tupl[7])
        self.sn = params[0].strip(b'\0').decode(encoding="ASCII", errors='ignore')
        self.comment = params[1].strip(b'\0').decode(encoding="ASCII", errors='ignore')
        self.node_id = params[2]
        self.dev_type = CHA_DEV_TYPE(params[3])
        self.vcxo_type = CHA_VCXO_TYPE(params[4])
        self.sync_src = CHA_SYNC_SRC(params[5])
        self.ext_out_0_en = params[6]
        self.ext_out_1_en = params[7]
        self.downlink_if = CHA_CONN_TYPE(params[8])
        self.downlink_wifi_ch = params[9]
        self.downlink_mac = params[10].hex()
        self.uplink_if = CHA_CONN_TYPE(params[11])
        self.uplink_wifi_ch = params[12]
        self.uplink_mac = params[13].hex()
        #self.wifi_power = params[14]
        #self.wifi_speed = SL_WLAN_RATE(params[15])
        #self.wifi_preamble = SL_WLAN_PREAMBLE(params[16])
        #self.wifi_cci = SlTxInhibitThreshold(params[17])

        # etc
        self.humidity = round(tupl[5], 1)
        self.temperature = round(tupl[6], 1)
        self.wifi_mac_downlink = tupl[8].hex()
        self.wifi_mac_uplink = tupl[9].hex()

class CHA_DISCOVERY_SLOT:
    SLOT_STRUCT = f'<{CHA_PARAMS_SN_SZ}sllBBBB6s6s6s6sBBxx'
    SLOT_SZ = struct.calcsize(SLOT_STRUCT)

    def __init__(self, slot_bytes):
        tupl = struct.unpack(CHA_DISCOVERY_SLOT.SLOT_STRUCT, slot_bytes)
        self.sn = tupl[0].strip(b'\0').decode(encoding="ASCII", errors='ignore')
        self.gps_lon = tupl[1]/10000000
        self.gps_lat = tupl[2]/10000000
        self.node_id = tupl[3]
        self.dev_type = CHA_DEV_TYPE(tupl[4])
        self.downlink_wifi_ch = tupl[5]
        self.uplink_wifi_ch = tupl[6]
        self.downlink_mac = tupl[7].hex()
        self.uplink_mac = tupl[8].hex()
        self.downlink_link = tupl[9].hex()
        self.uplink_link = tupl[10].hex()
        self.elapsed = tupl[11]
        self.avg_rssi = tupl[12]

class CHA_DISCOVERY_RESPONSE(CHA_RESPONSE):
    N_SLOTS = 8

    def __process_slot_bytes(self, slot_bytes):
        tupl = struct.unpack(CHA_DISCOVERY_RESPONSE.SLOT_STRUCT, slot_bytes)
        self.sn = tupl[0].strip(b'\0').decode(encoding="ASCII", errors='ignore')
        self.gps_lon = tupl[1]/10000000
        self.gps_lat = tupl[2]/10000000
        self.node_id = tupl[3]
        self.dev_type = CHA_DEV_TYPE(tupl[4])
        self.downlink_wifi_ch = tupl[5]
        self.uplink_wifi_ch = tupl[6]
        self.downlink_mac = tupl[7].hex()
        self.uplink_mac = tupl[8].hex()
        self.downlink_link = tupl[9].hex()
        self.uplink_link = tupl[10].hex()
        self.elapsed = tupl[11]
        self.avg_rssi = tupl[12]

    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)
        self.slots:list[CHA_DISCOVERY_RESPONSE] = list()
        slot_sz = CHA_DISCOVERY_SLOT.SLOT_SZ
        for i in range(CHA_DISCOVERY_RESPONSE.N_SLOTS):
            slot_bytes = payload_bytes[slot_sz*i:slot_sz*(i+1)]
            self.slots.append(CHA_DISCOVERY_SLOT(slot_bytes))

class CHA_SRM_TABLE_RESPONSE(CHA_RESPONSE):
    TABLE_HDR_STRUCT = '<6L16s'

    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)
        if self.hdr.chunk_n == 0 and self.hdr.nak_code == CHA_NAK_CODE.NO_ERROR: 
            self.hdr.wait_next_chunk = True
        self.payload = payload_bytes

    def concat_payloads(self, second_chunk:'CHA_SRM_TABLE_RESPONSE'):
        self.payload += second_chunk.payload

        hdr_sz = struct.calcsize(CHA_SRM_TABLE_RESPONSE.TABLE_HDR_STRUCT)
        tupl = struct.unpack(CHA_SRM_TABLE_RESPONSE.TABLE_HDR_STRUCT, self.payload[:hdr_sz])
        self.srm_sn = tupl[6].decode('ASCII').strip('\0')
        

