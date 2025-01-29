import time, logging, copy, queue
from config import PROGRAM_CONFIG
from device import CHASSIS
from nmea_true_time import TRUE_TIME
from protocol.cha_enums import *
from protocol.cs_enums import *
from protocol.cha_structs import *
from protocol.cs_structs import *
from stream_proc import STREAM_JOB

class LINRET_CORE:

    def __init__(self, program_params:PROGRAM_CONFIG, true_time:TRUE_TIME):
        self.program_params = program_params
        self.auto_request_data = program_params.get_auto_request_data()
        self.true_time = true_time
        self.log = logging.getLogger('CORE')
        self._queue = queue.Queue(maxsize=25)
        self.devices: dict[int, CHASSIS] = dict()
        self.serial = CS_SN(CS_DEV_TYPE.LR, 0, 0)
        self.log.info(f"Self CSERIAL: {bytes(self.serial).hex()}")
        self.adc_config = self.program_params.get_latest_adc_config()
        self.log.warning(str(self.adc_config))
        self.update_period = 0.2
        self.last_timeout_check_time = 0
        self.last_discover_time = 0
        self.last_sync_time = 0
        self.last_acq_ctl_time = 0
        self.next_job_schedule = None
        self.job_schedule_run = 0

        self.job_active = False
        self.next_stats_send = 0
        self.max_addr = dict()
        self.acq_ctl = 'do_nothing'
        self.discover_period = self.program_params.get_discover_period()
        for iface, max_nodes in self.program_params.get_max_nodes_per_iface().items():
            if max_nodes != 0: self.max_addr.update({CHA_LR_IF_TYPE[iface]:max_nodes})
        self.dbg_stats = {
            'cpu_temp': 0,
            'queue_full_drops': 0,
            'invalid_packets_drops': 0,
            'rx_packets_dropped': 0,
            'cs_rx_packet_errors': 0,
            'n_devs': 0,
            'update_time': time.monotonic()
        }

    def register_msg_handlres(self, to_cha, to_cs, to_str, to_mon):
        self.send_to_chassis = to_cha
        self.send_to_cs = to_cs
        self.send_to_str = to_str
        self.send_to_mon = to_mon

    def stats_sender(self, now):
        if now > self.next_stats_send:
            self.next_stats_send = now + 1

            self.dbg_stats['update_time'] = now
            self.dbg_stats['n_devs'] = len(self.devices)
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                self.dbg_stats['cpu_temp'] = int(f.read())/1000
            self.send_to_mon({'core_stats':copy.deepcopy(self.dbg_stats)})

            devs_stats = [CHASSIS.STATS_DIGEST_HDR]
            for dev in self.devices.values(): 
                devs_stats.append(dev.get_stats(now))

            self.send_to_mon({'devs_stats':devs_stats})

    def job_scheduler(self, now, true_time):
        if now < self.job_schedule_run: return
        if self.adc_config is None: return

        abs_time = int(true_time)
        if not self.next_job_schedule: 
            self.next_job_schedule = int(true_time) + 30
            return
        if abs_time < self.next_job_schedule: return
        self.next_job_schedule = abs_time + 1

        active_devs = dict()
        
        for dev in self.devices.values(): 
            if dev.is_active_dev(self.adc_config): 
                if dev.if_type not in active_devs: active_devs.update({dev.if_type:list()})
                active_devs[dev.if_type].append({
                    'addr':dev.addr, 'srm_serial_bytes':dev.srm_serial_bytes
                    })

        if self.auto_request_data and active_devs: 
            job = STREAM_JOB(self.send_to_chassis, self.send_to_mon, abs_time, self.adc_config, active_devs)
            #print("BBB")
            self.send_to_str(job)

    def acq_controller(self, mono_time, true_time):
        phase = true_time%1
        if (phase<0.4) or (phase>0.6): return
        if mono_time - self.last_acq_ctl_time < 1: return
        self.last_acq_ctl_time = mono_time

        if self.acq_ctl == 'run':
            for dev in self.devices.values(): dev.run_if_nesessary(true_time, self.adc_config)
        elif self.acq_ctl == 'stop':
            for dev in self.devices.values(): dev.stop_if_nesessary(true_time)
        else: return

    def nodes_syncer(self, mono_time, true_time):
        phase = true_time%1
        if (phase<0.4) or (phase>0.6): return
        if mono_time - self.last_sync_time < 1: return
        self.last_sync_time = mono_time
        for dev in self.devices.values():
            dev.sync_if_nesessary(true_time)

    def send_msg_to_core(self, msg):
        try: self._queue.put_nowait(msg)
        except queue.Full: self.dbg_stats['queue_full_drops'] += 1

    def main_loop(self):
        self.log.debug('Main loop start')
        while True:
            
            mono_time = time.monotonic()
            true_time = self.true_time.get_true_time()

            if true_time is not None:
                self.job_scheduler(mono_time, true_time)
                self.nodes_syncer(mono_time, true_time)
                self.acq_controller(mono_time, true_time)

            self.check_device_timeouts(mono_time)
            self.discover_next(mono_time)
            self.stats_sender(mono_time)

            try: msg = self._queue.get(timeout=0.1) #TODO - calc time to sleep
            except queue.Empty: continue

            if isinstance(msg, str):
                if msg == 'shutdown': break
                elif msg == 'job_active': self.job_active = True
                elif msg == 'job_finished': self.job_active = False
                elif msg == 'set_acq_ctl_mode__do_nothing': self.acq_ctl = 'do_nothing'
                elif msg == 'set_acq_ctl_mode__run': self.acq_ctl = 'run'
                elif msg == 'set_acq_ctl_mode__stop': self.acq_ctl = 'stop'
            elif isinstance(msg, CHA_RESPONSE): self.response_from_chassis(msg)
            elif isinstance(msg, CS_REQUEST): self.request_from_cs(msg)
            else: self.dbg_stats['invalid_packets_drops'] += 1

        self.log.debug('Main loop finish')

    def check_device_timeouts(self, now):
        if now - self.last_timeout_check_time < 0.1: return
        self.last_timeout_check_time = now

        timed_out_devs = list()
        
        for id, dev in self.devices.items(): 
            result = dev.check_timeouts(now, self.job_active)
            if result == 'timed_out': timed_out_devs.append(id)

        for id in timed_out_devs:
            self.log.info(f"{self.devices[id]} Lost")
            del self.devices[id]

    def discover_next(self, now):
        if self.job_active: return
        if now - self.last_discover_time < self.discover_period: return
        self.last_discover_time = now

        last_devs = dict()
        for if_type, max_addr in self.max_addr.items():
            if if_type not in last_devs:last_devs.update({if_type:list()})
            
        for dev in self.devices.values():
            last_devs[dev.if_type].append(dev.addr)

        for iface, max_addr in self.max_addr.items():
            full_set = set(range(1, max_addr + 1))
            devs_present = set(last_devs[iface])
            missing_devs = list(full_set - devs_present)

            if len(missing_devs) != 0:
                dst_addr = missing_devs[0]
                get_cha_state_pkt = CHA_STATE_REQUEST(iface, dst_addr, 0)
                #self.log.debug(f"Discovering {iface.name}:{dst_addr}")
                self.send_to_chassis(get_cha_state_pkt)


    def response_from_chassis(self, response:CHA_RESPONSE):
        full_addr = (response.hdr.if_type<<8) + response.hdr.src_addr
        if device := self.devices.get(full_addr):
            device.response_from_chassis(response)
        elif response.hdr.msg_type is CHA_MSG_TYPE.CNTL_STAT_ACK and \
                        response.hdr.nak_code is CHA_NAK_CODE.NO_ERROR:
            #new device discovered
            timeouts = self.program_params.get_nodes_timeouts()
            new_dev = CHASSIS(self.log, timeouts, self.send_to_chassis, response)
            self.devices.update({full_addr:new_dev})
            self.log.warning(f"{new_dev} Discovered")
            # discover next immediately
            next_request = CHA_STATE_REQUEST(new_dev.if_type, new_dev.addr+1, 0)
            self.send_to_chassis(next_request)
        else: 
            self.dbg_stats['rx_packets_dropped'] += 1

    def get_all_srms_list(self, now):
        retval = list()
        for dev in self.devices.values():
            if dev.srm_state is not None:
                retval.append(CS_DEV_ID(CS_DEV_TYPE.SRM, dev.srm_serial))

    def get_all_cha_list(self, cs_dev_type):
        retval = list()
        for dev in self.devices.values():
            if dev.cs_dev_type is cs_dev_type:
                #self.log.warning(f'{cs_dev_type.name}:{bytes(dev.cha_serial).hex()}')
                retval.append(CS_DEV_ID(cs_dev_type, dev.cha_serial))
        return retval

    def get_dev_by_serial(self, serial):
        #self.log.info(serial.hex())
        for dev in self.devices.values():
            #print(dev.cha_serial_bytes.hex())
            if serial in (dev.cha_serial_bytes, dev.srm_serial_bytes): return dev
        self.log.warning("No dev found for %s"%serial.hex())
        return None

    def request_from_cs(self, request:CS_REQUEST):
        now = time.monotonic()
        response = None

        if not request.hdr.broadcast: resp_hdr = request.hdr.response_hdr()
        else: resp_hdr = request.hdr.response_hdr(bytes(self.serial))

        if isinstance(request, CS_NODE_ID_LIST_REQUEST):
            #self.log.debug(f"CS REQUEST ID LIST: {request.dev_type}")
            if request.dev_type in (CS_DEV_TYPE.ANY, CS_DEV_TYPE.LR):
                lr_id = CS_DEV_ID(CS_DEV_TYPE.LR, self.serial)
                response = CS_NODE_ID_LIST_RESPONSE(resp_hdr, [lr_id])
            elif request.dev_type is CS_DEV_TYPE.SRM:
                response = CS_NODE_ID_LIST_RESPONSE(resp_hdr, self.get_all_srms_list(now))
            elif request.dev_type in (CS_DEV_TYPE.CHA_LR, CS_DEV_TYPE.CHA_RN):
                response = CS_NODE_ID_LIST_RESPONSE(resp_hdr, self.get_all_cha_list(request.dev_type))
            else:
                self.log.error(f'Got unexpected request ID for {request.dev_type.name}')
                self.dbg_stats['cs_rx_packet_errors'] += 1
            #if response: self.log.debug(response)

        elif request.hdr.cs_cmd_type is CS_PACKET_TYPE.LR_STATE_REQUEST:
            #self.log.debug(f"LR STATE REQUEST")
            response = CS_LR_STATE_RESPONSE(resp_hdr, self.serial.next_sn())

        elif request.hdr.cs_cmd_type is CS_PACKET_TYPE.SRM_STATE_REQUEST:
            #self.log.debug(f"SRM STATE REQUEST")
            if (dev := self.get_dev_by_serial(request.hdr.dst_serial_bytes)):
                srm_state = dev.get_srm_state(now)
                if srm_state:
                    #srm_state.adc_params = self.adc_config
                    response = CS_STATUS_SRM_RESPONSE(resp_hdr, srm_state)

        elif request.hdr.cs_cmd_type is CS_PACKET_TYPE.CHA_STATE_REQUEST:
            #self.log.debug(f"CHA RN STATE REQUEST")
            if (dev := self.get_dev_by_serial(request.hdr.dst_serial_bytes)):
                response = CS_STATUS_CHA_RN_RESPONSE(resp_hdr, 
                        dev.cha_serial, dev.srm_serial_bytes, dev.get_chassis_state(), dev.wifi_digest())
                
        elif request.hdr.cs_cmd_type is CS_PACKET_TYPE.CHA_LR_STATE_REQUEST:
            #self.log.debug(f"CHA LR STATE REQUEST: {msg.hdr.cs_cmd_type.name}")
            if (dev := self.get_dev_by_serial(request.hdr.dst_serial_bytes)):
                response = CS_STATUS_CHA_LR_RESPONSE(resp_hdr, 
                        dev.cha_serial, dev.srm_serial_bytes, dev.get_chassis_state(), dev.wifi_digest())

        elif isinstance(request, CS_ADC_CFG_SET_REQUEST):
            self.log.debug("SET CONFIG REQUEST")
            self.log.warning(f'New config set: {request.adc_cfg}')
            self.adc_config = request.adc_cfg
            response = CS_ACK_NAK_RESPONSE(resp_hdr, CS_ACK_CODE.ACK)

        elif isinstance(request, CS_CMD_ACQ_CONTROL_REQUEST):
            if request.hdr.broadcast:
                self.log.debug(f'BROADCAST acq ctl REQUEST: {request.acq_state.name}')
                for dev in self.devices.values():
                    if request.acq_state is CS_ACQ_STATE.IDLE:
                        dev.stop_if_nesessary(0)
                    elif request.acq_state is CS_ACQ_STATE.RUNNING:
                        dev.run_if_nesessary(self.adc_config)
                response = CS_ACK_NAK_RESPONSE(resp_hdr, CS_ACK_CODE.ACK)
                self.log.warning(f'Broadcast[{request.acq_state.name}]')

            else:
                self.log.warning(f'Acquisition ctl REQUEST: {request.acq_state.name}')
                if (dev := self.get_dev_by_serial(request.hdr.dst_serial_bytes)):
                    if request.acq_state is CS_ACQ_STATE.IDLE:
                        result = dev.stop_if_nesessary()
                    elif request.acq_state is CS_ACQ_STATE.RUNNING:
                        #result = dev.run_if_nesessary(self.adc_config)
                        result = 'OK'
                    if result == 'OK': 
                        response = CS_ACK_NAK_RESPONSE(resp_hdr, CS_ACK_CODE.ACK)
                    self.log.warning(f'Acquisition[{dev}][{request.acq_state.name}][{result}]')

        else:
            self.log.error(f'Unexpected cs_cmd_type: {request.hdr.cs_cmd_type}')
            self.dbg_stats['cs_rx_packet_errors'] += 1

        if response: self.send_to_cs(response)
        else: self.send_to_cs(CS_ACK_NAK_RESPONSE(resp_hdr, CS_ACK_CODE.NAK))
            


                
        
        
