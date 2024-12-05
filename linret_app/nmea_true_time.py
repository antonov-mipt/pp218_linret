import serial, pynmea2, time, datetime, threading, logging

ALLOWED_OFFSET_FROM_SYS_TIME_MS = None # set to None to disable comparison
NMEA_OFFSET = 0.14

class GPS_TIME:
    def __init__(self, log, rmc:pynmea2.RMC):
        self.log = log
        self.time = rmc.timestamp
        self.date = rmc.datestamp
        if self.time is None or self.date is None: return

        full_time = datetime.datetime.combine(self.date, self.time, datetime.timezone.utc)
        self.unix_time = full_time.timestamp() + NMEA_OFFSET
        self.timestamp = time.monotonic()
        self.system_time = time.time()
        self.valid = False

    def validate(self, gga:pynmea2.GGA):
        if self.time is None or self.date is None: return
        if self.time != gga.timestamp: return

        timediff = time.monotonic() - self.timestamp
        if timediff > 1: return

        if ALLOWED_OFFSET_FROM_SYS_TIME_MS is not None:
            offset_ms = int(1000*(self.system_time  - self.unix_time))
            if abs(offset_ms) > ALLOWED_OFFSET_FROM_SYS_TIME_MS:
                self.log.critical(f'!OFFSET! [{self.unix_time}]:[{offset_ms:d}ms]')
                return

        try: 
            qual = int(gga.gps_qual)
            numsats = int(gga.num_sats)
        except: 
            return 
        
        if (qual < 1) or (numsats < 2): return

        #print("AAA")
        return self.unix_time
        

class TRUE_TIME:
    
    TTY_DEV = '/dev/ttyS0'

    def __init__(self, use_system_time):
        self.s = serial.Serial(port = None, baudrate=9600, timeout=0.5, exclusive=True)
        self.s.port = TRUE_TIME.TTY_DEV
        self.opened = False
        self.open_err_printed = False
        self.nmea_parse_err_printed = False
        self.use_system_time = use_system_time
        self.log = logging.getLogger("TIME")
        if use_system_time: self.log.warning("Using NTP Time!")
        self.latest_time = None
        self.latest_mono = None
        self.shutdown = False
        self.t = threading.Thread(target=self.timesync_loop)
        
    def run(self):
        if not self.use_system_time:
            self.t.start()

    def join(self):
        self.shutdown = True
        if not self.use_system_time:
            self.t.join()

    def timesync_loop(self):
        t = None
        self.log.debug("True time thread started")
        open_time = None
        curr_gps_time = None

        while not self.shutdown:

            if not self.opened:
                try: 
                    self.s.open()
                    self.s.flush()
                    self.s.read(65536)
                    self.log.warning("Serial port for NMEA opened")
                    self.open_err_printed = False
                    self.opened = True
                    open_time = time.monotonic()
                except Exception as e:
                    if not self.open_err_printed:
                        self.log.error(f'Open serial port exception:\n\t{repr(e)}')
                        self.open_err_printed = True
                if not self.opened:
                    self.latest_time = None
                    self.latest_mono = None
                    time.sleep(1)
                    continue

            try:
                line = self.s.readline().decode('ascii', errors='replace').strip()
            except Exception as e:
                self.log.error(f'Read from serial failed:\n\t{repr(e)}')
                self.s.close()
                self.opened = False
                self.open_err_printed = False
                open_time = None
                continue

            if line == '':
                continue

            # skip first lines
            if (not open_time) or (time.monotonic() - open_time) < 1: 
                continue

            try:
                msg = pynmea2.parse(line)
            except Exception as e:
                if not self.nmea_parse_err_printed:
                    self.log.error(f'NMEA parse exception:\n\t{repr(e)}')
                    self.nmea_parse_err_printed = True
                continue

            #print(f'T[{time.time()}]:\n\t{repr(msg)}\n')

            if isinstance(msg, pynmea2.RMC):
                curr_gps_time = GPS_TIME(self.log, msg)

            if isinstance(msg, pynmea2.GGA) and (curr_gps_time is not None):
                if true_time := curr_gps_time.validate(msg):
                    if self.latest_time == None:
                        self.log.warning(f'Time base VALID:{true_time}')
                    self.latest_time = true_time
                    self.latest_mono = curr_gps_time.timestamp


        self.s.close()
        self.log.debug("True time thread finished")

    def get_true_time(self):
        if self.use_system_time: 
            return time.time()
        else:
            if self.latest_time is None or self.latest_mono is None: return
            offset = time.monotonic() - self.latest_mono
            if offset > 60: return
            else: return self.latest_time + offset