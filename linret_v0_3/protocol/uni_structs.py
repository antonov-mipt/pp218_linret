from __future__ import annotations
import struct
from enum import IntEnum
from .helpers import *
from .cs_enums import *

class SRM_DATARATE(IntEnum):
    DR_500 = 0
    DR_1000 = 1
    DR_2000 = 2

class REAL_DATARATE(IntEnum):
    DR_500 = 500
    DR_1000 = 1000
    DR_2000 = 2000

class UNI_ADC_CFG:
    CS_ADC_CFG_DATASTRUCT = '<BBH'
    SRM_ADC_CFG_DATASTRUCT = '<L'

    def __init__(self, rate:REAL_DATARATE, ch:list[int], gains:list[CS_GAIN_CODE]):
        self.adc_datarate = rate
        self.gains = gains
        self.ch_mask = ch
        self.to_srm_bytes() # to init code attr
        ch_en_packer = bit_pack()
        gain_packer = bit_pack()
        next(ch_en_packer)
        next(gain_packer)
        for i in range(4): 
            self.ch_bit_mask = ch_en_packer.send((self.ch_mask[i], 1))
            self.gain_bit_mask = gain_packer.send((self.gains[i], 4))
        self.n_ch = sum(self.ch_mask)

    @classmethod
    def from_cs_bytes(cls, inpt:bytes) -> UNI_ADC_CFG:
        rate, channels, gains = struct.unpack(cls.CS_ADC_CFG_DATASTRUCT, inpt)
        channels_unpacker = bit_unpack(channels)
        gain_unpacker = bit_unpack(gains)
        next(channels_unpacker)
        next(gain_unpacker)
        rate = REAL_DATARATE[CS_ADC_DR_CODE(rate).name]
        ch_mask = [channels_unpacker.send(1) for _ in range(4)]
        gains = [CS_GAIN_CODE(gain_unpacker.send(4)) for _ in range(4)]
        return cls(rate, ch_mask, gains)
        
    @classmethod
    def from_srm_bytes(cls, inpt:bytes) -> UNI_ADC_CFG:
        code = struct.unpack(cls.SRM_ADC_CFG_DATASTRUCT, inpt)[0]
        unpacker = bit_unpack(code)
        next(unpacker)
        rate = REAL_DATARATE[SRM_DATARATE(unpacker.send(2)).name]
        unpacker.send(14)
        ch_mask = [unpacker.send(1) for _ in range(4)]
        gains = [CS_GAIN_CODE(unpacker.send(3)) for _ in range(4)]
        return cls(rate, ch_mask, gains)
    
    @classmethod
    def from_config_json(cls, inpt:dict) -> UNI_ADC_CFG:
        rate = REAL_DATARATE(inpt.get('datarate', 500))
        ch_mask = inpt.get('ch_mask', [1,1,1,1])
        gains = [CS_GAIN_CODE(g) for g in inpt.get('gains', [0,0,0,0])]
        return cls(rate, ch_mask, gains) 

    def to_config_json(self):
        return {
            'datarate': self.adc_datarate.value,
            'ch_mask': self.ch_mask,
            'gains': [g.value for g in self.gains]
        }

    def to_cs_bytes(self):
        ch_en_packer = bit_pack()
        gain_packer = bit_pack()
        next(ch_en_packer)
        next(gain_packer)
        for i in range(4): 
            channels = ch_en_packer.send((self.ch_mask[i], 1))
            gains = gain_packer.send((self.gains[i], 4))
        
        return struct.pack(UNI_ADC_CFG.CS_ADC_CFG_DATASTRUCT,
            CS_ADC_DR_CODE[self.adc_datarate.name], channels, gains)
    
    def to_srm_bytes(self):       
        packer = bit_pack()
        next(packer)
        packer.send((SRM_DATARATE[self.adc_datarate.name], 2))
        packer.send((0, 14))
        #print(self.ch_mask)
        for i in range(4): packer.send((int(self.ch_mask[i]), 1))
        for i in range(4): self.code = packer.send((self.gains[i], 3))
        return struct.pack(UNI_ADC_CFG.SRM_ADC_CFG_DATASTRUCT, self.code)
    
    def datarate_value(self):
        return self.adc_datarate.value
    
    def packets_per_node(self):
        return self.adc_datarate*3*sum(self.ch_mask)//1500
    
    def __str__(self):
        ch_vals = list()
        for n, ch in enumerate(['X','Y','Z','H']):
            if self.ch_mask[n]: ch_vals.append(f'{ch}:{self.gains[n].name}')
        return f'[{self.adc_datarate.name}]' + ''.join(ch_vals)
    
    def __eq__(self, other):
        if isinstance(other, UNI_ADC_CFG):
            return self.code == other.code
        return False
    