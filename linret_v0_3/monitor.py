import asyncio, threading, os, time, logging, subprocess, io, math, bson
from datetime import datetime
from aiohttp import web
from config import PROGRAM_CONFIG
from nmea_true_time import TRUE_TIME

class HTTP_MONITOR:
    def __init__(self, true_time:TRUE_TIME, program_params:PROGRAM_CONFIG):
        self.port = program_params.get_web_ui_port()
        self.true_time = true_time
        self.log = logging.getLogger('MON')
        self.app = web.Application()
        self.static_files_dir = os.path.join(os.path.dirname(__file__), 'html')
        self.app.router.add_get('/chassis', self.get_chassis_stats)
        self.app.router.add_get('/cs', self.get_cs_stats)
        self.app.router.add_get('/core', self.get_core_stats)
        self.app.router.add_get('/devs', self.get_devs_stats)
        self.app.router.add_get('/stream', self.get_streamer_stats)
        self.app.router.add_get('/table', self.get_table_html)
        self.app.router.add_get('/stat', self.get_stat_html)
        self.app.router.add_get('/chrony', self.get_chrony_stats)
        self.app.router.add_get('/jobs', self.get_jobs_html)
        self.app.router.add_get('/jobs_stats', self.get_jobs_stats)
        #self.app.router.add_get('/plot', self.get_plot_html)
        #self.app.router.add_get('/plot_img', self.get_plot)
        self.app.router.add_get('/ws', self.websocket_handler)
        self.app.router.add_post('/update-mode', self.handle_update_mode)

        static_path = os.path.join(os.path.dirname(__file__), 'html')
        self.log.debug("Static filed dir: %s"%static_path)
        self.app.router.add_static('/', path=static_path, show_index=True)

        self.t = threading.Thread(target=self.run_server)
        self.run = lambda: self.t.start()
        self.join = lambda: self.t.join()
        self.loop = None
        self.stop_event = None
        self._queue = None
        self.ws_plot_queues = list()
        self.iface_chassis_stats = dict()
        self.iface_cs_stats = dict()
        self.core_stats = dict()
        self.devs_stats = list()
        self.streamer_stats = dict()
        self.jobs_stats = list()
        #self.latest_image = None

    def register_msg_handlres(self, to_core):
        self.send_to_core = to_core
    
    def send_msg_to_mon(self, msg):
        if self.loop != None and self._queue != None: 
            try: self.loop.call_soon_threadsafe(self._queue.put_nowait, msg)
            except asyncio.QueueFull: pass

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        q = asyncio.Queue(maxsize=5)
        self.ws_plot_queues.append(q)

        try:
            while True:
                job_data = await q.get()
                if not isinstance(job_data, dict): break

                timestamp = job_data['timestamp']
                human = str(datetime.utcfromtimestamp(timestamp))
                delay_ntp = time.time() - timestamp
                delay_gps = self.true_time.get_true_time() - timestamp
                delay_human = f'{human}\t||\t{timestamp}\t||\tNTP[{delay_ntp:.2f}]\t||\tGPS[{delay_gps:.2f}]'

                data = {
                    'samples':job_data['nodes_raw_bytes'],
                    'num_axes': job_data['adc_params'].n_ch,
                    'num_samples': job_data['adc_params'].adc_datarate.value,
                    'title': delay_human
                }

                bson_data = bson.BSON.encode(data)
                await ws.send_bytes(bson_data)

        except asyncio.CancelledError:
            print("WebSocket connection closed.")
        finally:
            self.ws_plot_queues.remove(q)
            await ws.close()
        return ws

    #async def get_plot(self, request):
    #    if self.latest_image is None: return web.Response(status=404)
    #    return web.Response(body=self.latest_image.generate_plot(0), content_type='image/jpeg')

    async def get_chassis_stats(self, request):
        return web.json_response(self.iface_chassis_stats)
    
    async def get_cs_stats(self, request):
        return web.json_response(self.iface_cs_stats)
    
    async def get_core_stats(self, request):
        return web.json_response(self.core_stats)
    
    async def get_devs_stats(self, request):
        return web.json_response(self.devs_stats)
    
    async def get_streamer_stats(self, request):
        return web.json_response(self.streamer_stats)
    
    async def get_jobs_stats(self, request):
        return web.json_response(self.jobs_stats)

    async def get_table_html(self, request):
        _html = os.path.join(self.static_files_dir, 'table.html')
        return web.FileResponse(_html)
    
    async def get_plot_html(self, request):
        _html = os.path.join(self.static_files_dir, 'plot.html')
        return web.FileResponse(_html)
    
    async def get_stat_html(self, request):
        _html = os.path.join(self.static_files_dir, 'stat.html')
        return web.FileResponse(_html)
    
    async def get_jobs_html(self, request):
        _html = os.path.join(self.static_files_dir, 'jobs.html')
        return web.FileResponse(_html)
    
    async def get_chrony_stats(self, request):
        chrony_outpt = await self.run_command('chronyc tracking')
        lines = chrony_outpt.decode().split('\n')
        return web.json_response(lines)
    
    async def handle_update_mode(self, request):
        try:
            data = await request.json()
            acq_ctl_mode = data['acq_ctl']
            print(acq_ctl_mode)
            if acq_ctl_mode == 'Do nothing': msg = 'set_acq_ctl_mode__do_nothing'
            elif acq_ctl_mode == 'Auto run': msg = 'set_acq_ctl_mode__run'
            elif acq_ctl_mode == 'Auto stop': msg = 'set_acq_ctl_mode__stop'
            self.send_to_core(msg)
            return web.json_response({"status": "success"})
        except Exception as e:
            return web.json_response({"status": "error", "message": repr(e)}, status=400)

    async def main_loop(self):
        self.webapp_runner = web.AppRunner(self.app)
        await self.webapp_runner.setup()
        self.webapp_site = web.TCPSite(self.webapp_runner, '', self.port)
        await self.webapp_site.start()

        logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

        while True:
            msg = await self._queue.get()
            if msg == 'shutdown': break

            if 'iface_chassis_stats' in msg:
                self.iface_chassis_stats = msg['iface_chassis_stats']

            if 'iface_cs_stats' in msg:
                self.iface_cs_stats = msg['iface_cs_stats']

            if 'core_stats' in msg:
                self.core_stats = msg['core_stats']

            if 'devs_stats' in msg:
                self.devs_stats = msg['devs_stats']

            if 'streamer_stats' in msg:
                self.streamer_stats = msg['streamer_stats']

            if 'jobs_stats' in msg:
                self.jobs_stats = msg['jobs_stats']

            if 'job_data' in msg:
                try:
                    for q in self.ws_plot_queues: q.put_nowait(msg['job_data'])
                    #self.latest_image = GENERATE_IMAGE(self.true_time, msg['job_data'])
                except Exception as e:
                    self.log.error(f'Exception in mon main loop:{repr(e)}')

        for q in self.ws_plot_queues: q.put_nowait('shutdown')
        await self.webapp_site.stop()
        await self.webapp_runner.shutdown()
        await self.webapp_runner.cleanup()

    def run_server(self):
        self.log.debug('MON loop start')
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._queue = asyncio.Queue()
        try: self.loop.run_until_complete(self.main_loop())
        except Exception as e: self.log.error(f"AIOLoop exception:\n\t{repr(e)}")
        self.log.debug('MON loop stop')

    async def run_command(self, command):
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return stdout
        else:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
