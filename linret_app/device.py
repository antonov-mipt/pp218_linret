import copy
from typing import Optional
from protocol.cha_enums import *
from protocol.cs_enums import *
from protocol.cha_structs import *
from protocol.cs_structs import *

class CHASSIS:
    STATS_TIMEOUT = 60

    def __init__(self, log, timeouts, request_to_chassis, state:CHA_STATE_RESPONSE):
        self.log = log
        self.timeouts = timeouts
        self.request_to_chassis = request_to_chassis
        self.addr = state.hdr.src_addr
        self.if_type = state.hdr.if_type
        self.was_in_stopped_state = True
        self.appended_unix_time = None
        self.synced = state.state_time_sync_ok if state.sync_src == CHA_SYNC_SRC.GPS else False
        self.sn = state.sn
        if self.if_type is CHA_LR_IF_TYPE.LOCAL: self.cs_dev_type = CS_DEV_TYPE.CHA_LR
        else: self.cs_dev_type = CS_DEV_TYPE.CHA_RN
        self.cha_serial = CS_SN(self.cs_dev_type, self.if_type, self.addr)
        self.srm_serial = None
        self.cha_serial_bytes = bytes(self.cha_serial)
        self.srm_serial_bytes = None
        self.full_addr = (self.if_type<<8) + self.addr
        self.random_id = 0
        self.cha_state:CHA_STATE_RESPONSE = state
        self.srm_state:Optional[CHA_SRM_STATUS_RESPONSE] = None
        self.discovery_state:Optional[CHA_DISCOVERY_RESPONSE] = None
        self.srm_fat_state:CHA_SRM_TABLE_RESPONSE = None
        self.time_to_request = lambda now, p: now > (p.recv_time+timeouts['packet_lifetime'])
        self.time_to_kill = lambda now, p: now > (p.recv_time+timeouts['node_total_lifetime'])
        self.still_pending = lambda now, r: now < (r.send_time+timeouts['packet_wait_timeout'])
        self.pending_requests:list[CHA_REQUEST] = list()
        self.stats = {'lats': dict(), 'rx': dict()
        }

    def send_and_update_random_id(self, request):
        self.random_id += 1
        if self.random_id == 256: self.random_id = 0
        #self.log.debug(f"{str(self)} sendig {msg_type}")
        self.pending_requests.append(request)
        self.request_to_chassis(request)

    def check_timeouts(self, now, job_is_active):
        if self.time_to_kill(now, self.cha_state): return 'timed_out'

        new_pending_requests = list()
        for r in self.pending_requests:
            if self.still_pending(now, r): new_pending_requests.append(r)
            else: self.stats['rx'].update({now:1})
        self.pending_requests = new_pending_requests

        keys_to_del = [key for key in self.stats['rx'] if now-key > CHASSIS.STATS_TIMEOUT]
        for key in keys_to_del:
            del self.stats['rx'][key]

        keys_to_del = [key for key in self.stats['lats'] if now-key > CHASSIS.STATS_TIMEOUT]
        for key in keys_to_del:
            del self.stats['lats'][key]

        if len(self.pending_requests) > 10: self.log.warning(f'{self} Too many pendings')

        if self.time_to_request(now, self.cha_state):
            packet = CHA_STATE_REQUEST(self.if_type, self.addr, self.random_id)
            self.send_and_update_random_id(packet)

        if self.srm_state is not None:
            #if self.time_to_kill(now, self.srm_state):
            #    self.srm_state = None
            pass

        if not job_is_active:

            if not self.srm_fat_state and self.srm_state:
                packet = CHA_SRM_TABLE_REQUEST(self.if_type, self.addr, self.random_id)
                self.send_and_update_random_id(packet)
        
            if (self.srm_state is None) or self.time_to_request(now, self.srm_state):
                packet = CHA_SRM_STATUS_REQUEST(self.if_type, self.addr, self.random_id)
                self.send_and_update_random_id(packet)

            if (self.srm_state is not None) and (not self.was_in_stopped_state):
                if self.srm_state.acq_running: self.acq_stop_cmd()
                else: self.was_in_stopped_state = True

            if not self.discovery_state or self.time_to_request(now, self.discovery_state):
                packet = CHA_DISCOVERY_REQUEST(self.if_type, self.addr, self.random_id)
                self.send_and_update_random_id(packet)



        return 'OK'

    def is_active_dev(self, active_adc_config):
        if self.srm_state is None: return False
        if self.srm_serial is None: return False
        if not self.srm_state.acq_running: return False
        if not self.srm_state.adc_sync_ok: return False
        if active_adc_config != self.srm_state.adc_params: return False
        return True
    
    def run_if_nesessary(self, true_time, active_adc_config:UNI_ADC_CFG):
        if not self.cha_state.chasis_time_valid: return 'error'
        if not self.cha_state.state_time_sync_ok: return 'error'
        if self.srm_state is None: return 'error'
        if self.srm_serial is None: return 'error'
        if not self.srm_state.pps_present: return 'error'
        if self.appended_unix_time is None: return 'error'
        if self.srm_state.acq_running: return 'OK'
        if active_adc_config is None: return 'error'
        
        self.log.info(f'{self} SRM RUN CMD at {true_time}')
        packet = CHA_SRM_RUN_REQUEST(self.if_type, self.addr, self.random_id, active_adc_config, self.cha_state.latest_valid_gps)
        self.send_and_update_random_id(packet)

        return 'OK'
    
    def stop_if_nesessary(self, true_time):
        if not self.srm_state: return 'error'
        if not self.srm_state.acq_running: return 'OK'
        if self.srm_state is None: return 'error'

        packet = CHA_SRM_STOP_REQUEST(self.if_type, self.addr, self.random_id)
        self.log.info(f'{self} SRM STOP CMD at {true_time}')
        self.send_and_update_random_id(packet)
        return 'OK'

    
    def sync_if_nesessary(self, true_unix_time):
        if self.appended_unix_time is not None: return

        #if self.cha_state.sync_src == CHA_SYNC_SRC.GPS: return
        if not self.cha_state.inpt_pps_valid: return

        self.log.warning(f'{self} need to sync...')

        cmd = CHA_SET_CLOCK_REQUEST(self.if_type, self.addr, self.random_id, true_unix_time)
        self.send_and_update_random_id(cmd)
        self.log.info(f'{self} SENT CMD SET CLOCK [{true_unix_time}]')

    def get_srm_state(self, now):
        if not self.srm_state: return None
        if self.time_to_kill(now, self.srm_state): return None
        return copy.copy(self.srm_state)
    
    def get_chassis_state(self):
        return self.cha_state
    
    def response_from_chassis(self, response:CHA_RESPONSE):
        now = time.monotonic()
        valid_packet_found = None
        for request in self.pending_requests:
            if valid_packet_found := request.validate_response(response): break

        if valid_packet_found:
            self.pending_requests.remove(request)
            self.stats['rx'].update({now:0})

            if response.hdr.msg_type == CHA_MSG_TYPE.CNTL_STAT_ACK:
                if response.hdr.nak_code != CHA_NAK_CODE.NO_ERROR:
                    self.log.warning(f'{request} {response.hdr.nak_code.name}')
                else:
                    self.cha_state = response
                    delay = response.recv_time - request.send_time
                    #time_offset = time.time() - delay - self.cha_state.curr_time
                    #print(time_offset)
                    self.stats['lats'].update({now:delay*1000})
                    
            elif response.hdr.msg_type == CHA_MSG_TYPE.SRM_STAT_ACK:
                if response.hdr.nak_code != CHA_NAK_CODE.NO_ERROR:
                    self.log.warning(f'{request} {response.hdr.nak_code.name}')
                else: 
                    self.srm_state = response
                    #print(time.time() - self.srm_state.unix_timestamp)
                    
            elif response.hdr.msg_type == CHA_MSG_TYPE.CNTL_NODES_BC_ACK:
                if response.hdr.nak_code != CHA_NAK_CODE.NO_ERROR:
                    self.log.warning(f'{request} {response.hdr.nak_code.name}')
                else: self.discovery_state = response

            elif response.hdr.msg_type == CHA_MSG_TYPE.SRM_RUN_ACK:
                if response.hdr.nak_code != CHA_NAK_CODE.NO_ERROR:
                    self.log.warning(f'{request} {response.hdr.nak_code.name}')
                else: pass

            elif response.hdr.msg_type == CHA_MSG_TYPE.CNTL_CLK_SET_ACK:
                if response.phase is not None:
                    req_ph = int((request.true_unix_time%1)*1000)
                    resp_ph = response.phase//1000000
                    diff = req_ph - resp_ph
                    self.log.info(f'{self} SYNC {req_ph}ms {resp_ph}ms {diff}ms')
                    if abs(diff) < 100:
                        self.synced = True
                        self.appended_unix_time = request.second
                        self.log.warning(f'{self} SYNC OK {req_ph}ms {resp_ph}ms {diff}ms')
                    else:
                        self.log.info(f'{self} SYNC FAILED {req_ph}ms {resp_ph}ms {diff}ms')
                        self.synced = False
                        self.appended_unix_time = None

            elif response.hdr.msg_type == CHA_MSG_TYPE.SRM_FAT_ACK:
                if response.hdr.nak_code != CHA_NAK_CODE.NO_ERROR:
                    self.log.warning(f'{request} {response.hdr.nak_code.name}')
                else:
                    self.srm_fat_state = response
                    self.srm_serial = response.srm_sn
                    self.srm_serial_bytes = response.srm_sn[-CS_SERIAL_SZ:].encode("ASCII")
                    self.log.warning(f'{self} SRM serial: {self.srm_serial}')

    def wifi_digest(self):
        retval = {'downlink':None, 'uplink':None}
        if not self.discovery_state: return retval

        for slot in self.discovery_state.slots:
            if self.cha_state.wifi_mac_uplink in (slot.uplink_link, slot.downlink_link):
                retval['uplink'] = CS_WIFI_SLOT(slot.avg_rssi, slot.gps_lon, slot.gps_lat)
            if self.cha_state.wifi_mac_downlink == slot.uplink_link:
                retval['downlink'] = CS_WIFI_SLOT(slot.avg_rssi, slot.gps_lon, slot.gps_lat)

        return retval

    def get_stats(self, now):
        wifi_digest = self.wifi_digest()

        def batt_state(volt):
            if volt > 15: color = 'green'
            elif volt > 14: color = 'yellow'
            else: color = 'red'
            return {'txt':f'{volt:.2f}', 'color': color}

        def wifi_state_uplink():
            if self.cha_state.uplink_if is CHA_CONN_TYPE.WIRELESS and wifi_digest['uplink']:
                ch = str(self.cha_state.uplink_wifi_ch)
                rssi = wifi_digest['uplink'].rssi if wifi_digest['uplink'] else '---'
                link = self.cha_state.sys_wifi_link0_ok
                return {'txt':f'{ch}:{rssi}', 'color':'green' if link else 'red'}
            else: return {'txt':'', 'color': 'orange'}

        def wifi_state_downlink():
            if self.cha_state.downlink_if is CHA_CONN_TYPE.WIRELESS and wifi_digest['downlink']:
                ch = str(self.cha_state.downlink_wifi_ch)
                rssi = wifi_digest['downlink'].rssi if wifi_digest['downlink'] else '---'
                link = self.cha_state.sys_wifi_link1_ok
                return {'txt':f'{ch}:{rssi}', 'color':'green' if link else 'red'}
            else: return {'txt':'', 'color': 'orange'}

        def srm_pps_state():
            txt, color = '', ''
            if self.srm_state:
                if self.srm_state.pps_present:
                    #ts = self.srm_state.pps_timestamp_ns/1000000000
                    #offset = ts%1
                    #txt = f'{offset*1000:.2f}ms'
                    #if (offset<0.0001) or (offset>0.9999): color = 'yellow'
                    #else: 
                    color = 'green'
                else: color = 'red'
            return {'txt':txt, 'color':color}

        sd_color, adc_txt, adc_color = '', '', ''
        if self.srm_state:
            sd_color = 'green' if self.srm_state.sd_ok else 'red'
            if self.srm_state.acq_running:
                params = self.srm_state.adc_params
                adc_txt = f'{params.adc_datarate.value}/{params.n_ch}'
                if self.srm_state.sd_record_running and self.srm_state.adc_sync_ok: 
                    adc_color = 'green'
                else: adc_color = 'red'

        def get_srm_state():
            if not self.srm_state: 
                return {'txt':'', 'color':'red'}
            elif self.srm_serial is None:
                return {'txt':'', 'color':'orange'}
            else:
                return {'txt': self.srm_serial[4:], 'color':'green'}

        def gps_state():
            if self.cha_state.gps.num_sv > 3: color = 'green'
            elif self.cha_state.gps.num_sv > 2: color = 'yellow'
            else: color = 'red'
            return {'txt':str(self.cha_state.gps.num_sv), 'color': color}
        
        def link_stat(s):
            if len(s['rx']) == 0: 
                lost_txt = '---'
            else: 
                loss = sum(self.stats['rx'].values())/len(self.stats['rx'])
                lost_txt = str(int(loss*100)) + '%'

            if len(s['lats']) == 0: 
                lat_txt = '---'
            else: 
                lats = sum(s['lats'].values())/len(s['lats'])
                lat_txt = str(int(lats)) + 'ms'

            return {'txt':f'{lost_txt}/{lat_txt}', 'color':''}
        
        def sync_stat():
            txt = self.cha_state.sync_src.name
            if not self.cha_state.chasis_time_valid: color = 'red'
            elif self.appended_unix_time is None: color = 'yellow'
            else: color = 'green'
            return {'txt':txt, 'color':color} 

        return [
            {'txt':self.if_type.name, 'color':''},
            {'txt':'%02u'%self.addr, 'color':''},
            {'txt':self.sn[-5:], 'color':''},
            gps_state(),
            sync_stat(),
            batt_state(self.cha_state.batt_vin[0]), batt_state(self.cha_state.batt_vin[1]),
            wifi_state_uplink(), wifi_state_downlink(),
            get_srm_state(),
            srm_pps_state(),
            {'txt':'', 'color': sd_color},
            {'txt':adc_txt, 'color': adc_color},
            link_stat(self.stats)
        ]

    STATS_DIGEST_HDR = [{'txt':v} for v in [
        'IF','ADDR','SN','GPS','SYNC','BAT0','BAT1','CH0','CH1','SRM','PPS','SD','ADC','STAT'
        ]]

    def __str__(self):
        return f"{self.cs_dev_type.name}:{self.addr}:{self.sn}"