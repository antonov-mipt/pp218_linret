import struct
from enum import IntEnum
from .cs_enums import *
from .helpers import *
from .uni_structs import *
from .cha_structs import *
from .sn_emulator import *

CS_SERIAL_SZ = 8

class CS_DEV_ID:
    def __init__(self, dev_type:CS_DEV_TYPE, serial:CS_SN):
        self.dev_type = dev_type
        self.serial_bytes = bytes(serial)
    
    def __bytes__(self):
        return struct.pack(f'<BBH{CS_SERIAL_SZ}s', 0, 0, self.dev_type, self.serial_bytes)

'''
Header
'''
class CS_PROTO_HDR:
    CS_HDR_STRUCT = f'<BBBB{CS_SERIAL_SZ}s{CS_SERIAL_SZ}sL'
    CS_PROTO_HDR_SZ = struct.calcsize(CS_HDR_STRUCT)
    CS_PROTO_MAGIC = 0x3A
    CS_PROTO_VER = 0x04



    def __init__(self, inpt:bytes):
        tupl = struct.unpack(CS_PROTO_HDR.CS_HDR_STRUCT, inpt)
        if tupl[0] != CS_PROTO_HDR.CS_PROTO_MAGIC or tupl[1] != CS_PROTO_HDR.CS_PROTO_VER:
            raise ValueError("Invalid CS HDR")
        self.broadcast = (tupl[5] == b'\xFF'*CS_SERIAL_SZ)
        self.cs_cmd_type = CS_PACKET_TYPE(tupl[2])
        self.session_id = tupl[3]
        self.src_serial_bytes = tupl[4]
        self.dst_serial_bytes = tupl[5] if not self.broadcast else b'\xFF'*CS_SERIAL_SZ
        self.payload_length = tupl[6]
    
    def __bytes__(self):
        #print(self.cs_cmd_type, self.session_id,
        #      self.src_serial_bytes, self.dst_serial_bytes, self.payload_length )
        return struct.pack(CS_PROTO_HDR.CS_HDR_STRUCT, 
                CS_PROTO_HDR.CS_PROTO_MAGIC, CS_PROTO_HDR.CS_PROTO_VER,
                self.cs_cmd_type,
                self.session_id,
                self.src_serial_bytes, self.dst_serial_bytes,
                self.payload_length
            )

    def response_hdr(self, src_serial_bytes=None):
        resp = CS_PROTO_HDR(bytes(self))
        resp.session_id = self.session_id
        resp.dst_serial_bytes = self.src_serial_bytes
        if not src_serial_bytes: 
            resp.src_serial_bytes = self.dst_serial_bytes
        elif type(src_serial_bytes) == bytes:
            resp.src_serial_bytes = src_serial_bytes  
        else: 
            raise RuntimeError("Incorrect src serial")
        return resp

'''
Requests
'''
class CS_REQUEST:
    def __init__(self, hdr:CS_PROTO_HDR, payload_bytes: bytes):
        self.hdr = hdr
        self.payload_bytes = payload_bytes

class CS_NODE_ID_LIST_REQUEST(CS_REQUEST):
    def __init__(self, *args):
        super().__init__(*args)
        dev = struct.unpack('<H',self.payload_bytes)[0]
        self.dev_type = CS_DEV_TYPE(dev)

    def __str__(self):
        return f"Node ID list request for {self.dev_type.name}"

class CS_ADC_CFG_SET_REQUEST(CS_REQUEST):
    def __init__(self, *args):
        super().__init__(*args)
        self.adc_cfg = UNI_ADC_CFG.from_cs_bytes(self.payload_bytes)

class CS_CMD_ACQ_CONTROL_REQUEST(CS_REQUEST):
    def __init__(self, *args):
        super().__init__(*args)
        acq_code, test_code = struct.unpack('<BB', self.payload_bytes)
        self.acq_state = CS_ACQ_STATE(acq_code)
        self.test_signal = CS_TEST_SIGNAL(test_code)

'''
Responces
'''
class CS_RESPONSE:
    def __init__(self, hdr:CS_PROTO_HDR, pack_type:CS_PACKET_TYPE):
        self.hdr = hdr
        self.hdr.cs_cmd_type = pack_type
    
class CS_NODE_ID_LIST_RESPONSE(CS_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, devs_list: list):
        super().__init__(hdr, CS_PACKET_TYPE.NODE_ID_LIST_RESPONSE)
        self.devs_list = devs_list

    def __bytes__(self):
        bytes_n_records = struct.pack('<H', len(self.devs_list))
        byte_devs_array = [bytes(dev) for dev in self.devs_list]
        payload_bytes = bytes_n_records + b''.join(byte_devs_array)
        self.hdr.payload_length = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes
    
    def __str__(self):
        return f'Node ID list response for {len(self.devs_list)} devs'
    
class CS_ACK_NAK_RESPONSE(CS_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, ack:CS_ACK_CODE):
        super().__init__(hdr, CS_PACKET_TYPE.ACK_NAK_RESPONSE)
        self.ack = ack

    def __bytes__(self):
        payload_bytes = bytes([self.ack])
        self.hdr.payload_length = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes
    
class CS_LR_STATE_RESPONSE(CS_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, serial:CS_SN):
        super().__init__(hdr, CS_PACKET_TYPE.LR_STATE_REQPONSE)
        self.serial = serial

    def __bytes__(self):
        payload_bytes = bytes(self.serial)
        self.hdr.payload_length = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes

class CS_STATUS_SRM_RESPONSE(CS_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, srm_state:CHA_SRM_STATUS_RESPONSE):
        super().__init__(hdr, CS_PACKET_TYPE.SRM_STATE_RERESPONSE)
        self.adc_config = srm_state.adc_params
        
        if srm_state.acq_running: self.acquisition_running = CS_ACQ_STATE.RUNNING 
        else: self.acquisition_running = CS_ACQ_STATE.IDLE 

        self.temperature = CS_TEMPERATURE(srm_state.temperature)
        self.humidity = CS_HUMIDITY(srm_state.humidity)
        
        if srm_state.pps_present: self.sync_ok = CS_SRM_SYNC_STATE.SYNC
        else: self.sync_ok = CS_SRM_SYNC_STATE.NO_SYNC

        self.test_signal = CS_TEST_SIGNAL.NO_SIGNAL

    def __bytes__(self):
        payload_bytes = struct.pack('<L4sBbBBB', 0,
            self.adc_config.to_cs_bytes(),
            self.acquisition_running,
            self.temperature, self.humidity,
            self.sync_ok, self.test_signal,
        )
        self.hdr.payload_length = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes

class CS_WIFI_SLOT:
    def __init__(self, rssi, lon, lat):
        self.rssi = rssi
        self.lon, self.lat = lon, lat
        self.state = CS_WIFI_CLIENT_STATE.LINKED

    def __bytes__(self):
        return struct.pack(f'<B{CS_SERIAL_SZ}sBff', 
            CS_WIFI_CLIENT_STATE.LINKED, bytes(self.serial), self.rssi, self.lon, self.lat)
    
class CS_STATUS_CHA_RESPONSE(CS_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, cha_serial:CS_SN, srm_ser_bytes, cha_state:CHA_STATE_RESPONSE, cmd_resp:CS_PACKET_TYPE):
        super().__init__(hdr, cmd_resp)
        self.self_serial = cha_serial
        self.bat0_state = CS_BAT_STATE.PRESENT
        self.bat1_state = CS_BAT_STATE.PRESENT
        self.wifi_clients = list()
        self.batt_volts = cha_state.batt_vin
        if cha_state.state_srm_connected and srm_ser_bytes is not None: 
            self.srm_serial = srm_ser_bytes
        else: self.srm_serial = b'\x00'*CS_SERIAL_SZ
        if cha_state.gps.num_sv > 3:
            self.longitude = cha_state.gps.gps_lon
            self.latitule = cha_state.gps.gps_lat
            self.height = cha_state.gps.gps_height
        else:
            self.longitude, self.latitule, self.height = 0, 0, 0
        self.temp, self.humidity = cha_state.temperature, cha_state.humidity

    def wifi_slot_bytes(self):
        n_clients_byte = bytes([len(self.wifi_clients)])
        client_bytes = list()
        for client in self.wifi_clients:
            client_bytes.append(bytes(client))
        return n_clients_byte + b''.join(client_bytes)
    
    def batt_state_code(self, v0, v1):
        packer = bit_pack()
        next(packer)
        packer.send((v0, 4))
        return packer.send((v1, 4))

         
class CS_STATUS_CHA_RN_RESPONSE(CS_STATUS_CHA_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, cha_serial:CS_SN, srm_ser_bytes, cha_state:CHA_STATE_RESPONSE, wifi:dict):
        super().__init__(hdr, cha_serial, srm_ser_bytes, cha_state, CS_PACKET_TYPE.CHA_STATE_RESPONSE)
        
        if cha_state.mode_obs: self.dev_type = CS_DEV_TYPE.CHA_RN_SEA
        else: self.dev_type = CS_DEV_TYPE.CHA_RN_LAND

        if cha_state.uplink_if == CHA_CONN_TYPE.WIRED:
            self.wired_conn1_serial = bytes(cha_serial.prev_sn())
        else: self.wired_conn1_serial = b'\x00'*CS_SERIAL_SZ

        if cha_state.downlink_if == CHA_CONN_TYPE.WIRED:
            self.wired_conn2_serial = bytes(cha_serial.next_sn())
        else: self.wired_conn2_serial = b'\x00'*CS_SERIAL_SZ

        if cha_state.uplink_if == CHA_CONN_TYPE.WIRELESS and wifi['uplink']:
            self.wifi_uplink_serial = bytes(cha_serial.prev_sn())
            self.wifi_uplink_rssi = wifi['uplink'].rssi
            self.wifi_uplink_link = CS_WIFI_CLIENT_STATE.LINKED
        else: 
            self.wifi_uplink_serial = b'\x00'*CS_SERIAL_SZ
            self.wifi_uplink_rssi = 0
            self.wifi_uplink_link = CS_WIFI_CLIENT_STATE.NOT_LINKED

        if cha_state.downlink_if == CHA_CONN_TYPE.WIRELESS and wifi['downlink']:
            wifi['downlink'].serial = cha_serial.next_sn()
            self.wifi_clients.append(wifi['downlink'])

    def __bytes__(self):
        payload_bytes = struct.pack(f'<L H BBB {CS_SERIAL_SZ}s{CS_SERIAL_SZ}s B{CS_SERIAL_SZ}sB ff {CS_SERIAL_SZ}s BB',
            0, # err code
            self.dev_type,
            self.batt_state_code(self.bat0_state, self.bat1_state), 
            CS_BAT_VOLTAGE(self.batt_volts[0]), CS_BAT_VOLTAGE(self.batt_volts[1]),
            self.wired_conn1_serial, self.wired_conn2_serial,
            self.wifi_uplink_link, self.wifi_uplink_serial, self.wifi_uplink_rssi,
            self.longitude, self.latitule,
            self.srm_serial,
            CS_TEMPERATURE(self.temp), CS_HUMIDITY(self.humidity)
            )
        
        wifi_bytes = self.wifi_slot_bytes()
        self.hdr.payload_length = len(payload_bytes) + len(wifi_bytes)
        return bytes(self.hdr) + payload_bytes + wifi_bytes


class CS_STATUS_CHA_LR_RESPONSE(CS_STATUS_CHA_RESPONSE):
    def __init__(self, hdr:CS_PROTO_HDR, cha_serial:CS_SN, srm_ser_bytes, cha_state:CHA_STATE_RESPONSE, wifi:dict):
        super().__init__(hdr, cha_serial, srm_ser_bytes, cha_state, CS_PACKET_TYPE.CHA_LR_STATE_RESPONSE)
        
        if cha_state.mode_obs: self.dev_type = CS_DEV_TYPE.CHA_LR_SEA
        else: self.dev_type = CS_DEV_TYPE.CHA_LR_LAND

        if cha_state.hw_batt_0_charging: self.bat0_state = CS_BAT_STATE.CHARGING
        else: self.bat0_state = CS_BAT_STATE.DISCHARGING
        
        if cha_state.hw_batt_0_charging: self.bat1_state = CS_BAT_STATE.CHARGING
        else: self.bat1_state = CS_BAT_STATE.DISCHARGING

        #if cha_state.uplink_if == CHA_CONN_TYPE.WIRED:
        new_sn = cha_serial.next_sn(new_if_type=CHA_LR_IF_TYPE.WIRED_0)
        self.wired_conn1_serial = bytes(new_sn)
        #else: self.wired_conn1_serial = b'\x00'*CS_SERIAL_SZ

        #if cha_state.downlink_if == CHA_CONN_TYPE.WIRED:
        new_sn = cha_serial.next_sn(new_if_type=CHA_LR_IF_TYPE.WIRED_1)
        self.wired_conn2_serial = bytes(new_sn)
        #else: self.wired_conn2_serial = b'\x00'*CS_SERIAL_SZ

        if cha_state.uplink_if == CHA_CONN_TYPE.WIRELESS and wifi['uplink']:
            new_sn = cha_serial.next_sn(new_if_type=CHA_LR_IF_TYPE.WIFI_0)
            wifi['uplink'].serial = new_sn
            self.wifi_clients.append(wifi['uplink'])

        if cha_state.downlink_if == CHA_CONN_TYPE.WIRELESS and wifi['downlink']:
            new_sn = cha_serial.next_sn(new_if_type=CHA_LR_IF_TYPE.WIFI_1)
            wifi['downlink'].serial = new_sn
            self.wifi_clients.append(wifi['downlink'])

        self.conn_to_cs = SN_EMULATOR().cs_serial_bytes
        if self.conn_to_cs == None: self.conn_to_cs = b'\x00'*CS_SERIAL_SZ

    CHA_LR_STAT_DATASTRUCT = f'<L H BBB {CS_SERIAL_SZ}s{CS_SERIAL_SZ}s {CS_SERIAL_SZ}s{CS_SERIAL_SZ}s{CS_SERIAL_SZ}s{CS_SERIAL_SZ}s ff {CS_SERIAL_SZ}s BB'

    def __bytes__(self):
        payload_bytes = struct.pack(CS_STATUS_CHA_LR_RESPONSE.CHA_LR_STAT_DATASTRUCT,
            0, # err code
            self.dev_type,
            self.batt_state_code(self.bat0_state, self.bat1_state), 
            CS_BAT_VOLTAGE(self.batt_volts[0]), CS_BAT_VOLTAGE(self.batt_volts[1]),
            self.wired_conn1_serial, self.wired_conn2_serial,
            self.conn_to_cs, b'\x00'*CS_SERIAL_SZ, b'\x00'*CS_SERIAL_SZ, b'\x00'*CS_SERIAL_SZ,
            self.longitude, self.latitule,
            self.srm_serial,
            CS_TEMPERATURE(self.temp), CS_HUMIDITY(self.humidity)
            )
        
        wifi_bytes = self.wifi_slot_bytes()
        self.hdr.payload_length = len(payload_bytes) + len(wifi_bytes)
        return bytes(self.hdr) + payload_bytes + wifi_bytes