import json, logging
from protocol.uni_structs import UNI_ADC_CFG

class PROGRAM_CONFIG:

    def __init__(self, filename):
        self.config_valid = False
        self.log = logging.getLogger('CFG')
        self.config = {}
        self.fliename = filename
        self.load_config()

    def __str__(self):
        return json.dumps(self.config, indent=4)

    def load_config(self):
        try:
            with open(self.fliename, 'r') as file:
                self.config = json.load(file)
                self.config_valid = True
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.log.critical(f'Load config exception: {repr(e)}')
                  

    def save_config(self):
        try:
            with open(self.fliename, 'w') as file:
                json.dump(self.config, file, indent=4)
        except IOError as e:
            self.log.error(f'Load config exception: {repr(e)}') 

    def save_new_adc_config(self, adc_cfg:UNI_ADC_CFG):
        self.config.update({
            'latest_adc_config': adc_cfg.to_config_json()
        })
        self.log.warning(f'ADC config updated: f{adc_cfg}')
        self.save_config()
        
    def get_latest_adc_config(self):
        cfg =self.config.get('latest_adc_config')
        if not cfg: return None
        else: return UNI_ADC_CFG.from_config_json(cfg)

    def get_web_ui_port(self):
        if 'web_ui_port' not in self.config:
            self.config.update({'web_ui_port':8000})
            self.save_config()
        return self.config['web_ui_port']

    def get_cs_port(self):
        if 'cs_port' not in self.config:
            self.config.update({'cs_port':56987})
            self.save_config()
        return self.config['cs_port']
    
    def get_eth_iface(self):
        if 'eth_iface' not in self.config:
            self.config.update({'eth_iface':'eth2'})
            self.save_config()
        return self.config['eth_iface']

    def get_lr_n(self):
        if 'lr_number' not in self.config:
            self.config.update({'lr_number':1})
            self.save_config()
        return self.config['lr_number']
    
    def get_chassis_mac(self):
        if 'chassis_mac' not in self.config:
            self.config.update({'chassis_mac':b'pp218\0'.hex()})
            self.save_config()
        return bytes.fromhex(self.config['chassis_mac'])
    
    def get_db_config(self):
        if 'db_config' not in self.config:
            self.config.update({'db_config':{
                'url': 'mongodb://192.168.1.53:27017',
                'db_name': 'lr_data',
                'data_collection': 'node_data',
                'timecache_collection': 'node_data_time_cache'
            }})
            self.save_config()
        return self.config['db_config']
    
    def get_auto_request_data(self):
        if 'auto_request_data' not in self.config:
            self.config.update({'auto_request_data':False})
            self.save_config()
        return self.config['auto_request_data']
    
    def get_use_system_time(self):
        if 'use_system_time' not in self.config:
            self.config.update({'use_system_time':False})
            self.save_config()
        return self.config['use_system_time']
    
    def get_max_nodes_per_iface(self):
        apply_changes = False
        if 'max_nodes_per_interface' not in self.config:
            self.config.update({'max_nodes_per_interface':{}})
            apply_changes = True
        max_nodes = self.config['max_nodes_per_interface']
        if 'LOCAL' not in max_nodes:
            max_nodes.update({'LOCAL':1})
            apply_changes = True
        if 'WIFI_0' not in max_nodes:
            max_nodes.update({'WIFI_0':0})
            apply_changes = True
        if 'WIFI_1' not in max_nodes:
            max_nodes.update({'WIFI_1':0})
            apply_changes = True
        if 'WIRED_0' not in max_nodes:
            max_nodes.update({'WIRED_0':0})
            apply_changes = True
        if 'WIRED_1' not in max_nodes:
            max_nodes.update({'WIRED_1':0})
            apply_changes = True

        if apply_changes: self.save_config()
        return max_nodes
    
    def get_discover_period(self):
        if 'nodes_discover_period' not in self.config:
            self.config.update({'nodes_discover_period':1})
            self.save_config()
        return self.config['nodes_discover_period']
    
    def get_nodes_timeouts(self):
        if 'node_timeouts' not in self.config:
            self.config.update({'node_timeouts':{
                'node_total_lifetime': 10,
                'packet_wait_timeout': 0.15,
                'packet_lifetime': 0.75
            }})
            self.save_config()
        return self.config['node_timeouts']
    
    def get_delay_between_requests(self):
        if 'delay_between_requests' not in self.config:
            self.config.update({
                'delay_between_requests':0.15
            })
            self.save_config()
        return self.config['delay_between_requests']
    
    def get_delay_before_request(self):
        if 'delay_before_request' not in self.config:
            self.config.update({
                'delay_before_request':2.4
            })
            self.save_config()
        return self.config['delay_before_request']