import struct
from .cs_enums import CS_DEV_TYPE
from .cha_enums import CHA_LR_IF_TYPE

class SN_EMULATOR:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SN_EMULATOR, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, LR_NUM= None, CS_SN=None):
        if LR_NUM: self.lr_sn = LR_NUM
        if CS_SN: self.cs_serial_bytes = CS_SN

    def generate(self, dev:CS_DEV_TYPE, if_type:CHA_LR_IF_TYPE, addr):
        shft = b'0'[0]
        return struct.pack('<4sBBBB', b'EMU_', self.lr_sn+shft, dev, if_type+shft, addr+shft)
    

class CS_SN:
    def __init__(self, dev:CS_DEV_TYPE, if_type, addr):
        self.dev = dev
        self.if_type = if_type
        self.addr = addr
        self.gen = SN_EMULATOR()

    def __bytes__(self):
        return self.gen.generate(self.dev, self.if_type, self.addr)
    
    def next_sn(self, new_if_type = None):
        if self.dev == CS_DEV_TYPE.LR:
            # следующий - шасси ЛР
            return CS_SN(CS_DEV_TYPE.CHA_LR, CHA_LR_IF_TYPE.LOCAL, 1)
        elif self.dev == CS_DEV_TYPE.CHA_LR:
            # следующий - шасси РН с адресом 1 и заданным интерфейсом
            return CS_SN(CS_DEV_TYPE.CHA_RN, new_if_type, 1)
        elif self.dev == CS_DEV_TYPE.CHA_RN:
            # следующий - шасси РН с инкрементом адреса и тем же интерфейсом
            return CS_SN(CS_DEV_TYPE.CHA_RN, self.if_type, self.addr+1)
        else:
            raise RuntimeError("Unexpected dev type in next_sn")
    
    def prev_sn(self):
        if self.dev == CS_DEV_TYPE.CHA_LR:
            # предыдущий - ЛР
            return self.gen.cs_serial_bytes
        elif self.dev == CS_DEV_TYPE.CHA_RN:
            if self.addr > 1:
                # предыдущий в шасси РН с декрементом адреса
                return CS_SN(CS_DEV_TYPE.CHA_RN, self.if_type, self.addr-1)
            elif self.addr == 1:
                # предыдущий в шасси ЛР
                return CS_SN(CS_DEV_TYPE.CHA_LR, CHA_LR_IF_TYPE.LOCAL, 1)
            raise RuntimeError("Unexpected addr type in prev_sn") 
        else:
            raise RuntimeError("Unexpected dev type in prev_sn")
        
    def srm_sn(self):
        return CS_SN(CS_DEV_TYPE.SRM, self.if_type, self.addr)

        
