from .cha_structs import *

'''
Helpers
'''

split_to_words = lambda n: (n>>5, 1<<(n&0x1F))

def bit_set(mask:list[int], bit_n:int):
    cell, bit = split_to_words(bit_n)
    mask[cell] |= bit

def bit_clear(mask:list[int], bit_n:int):
    cell, bit = split_to_words(bit_n)
    mask[cell] &= (~bit)&0xFFFFFFFF

def bit_read(mask:list[int], bit_n:int):
    cell, bit = split_to_words(bit_n)
    return bool(mask[cell]&bit)

'''
REQUESTS
'''

class STREAM_START_REQUEST(CHA_REQUEST):
    BITMASK_SZ_32 = 13
    DATASTRUCT = f'<L{BITMASK_SZ_32}LL'

    def __init__(self, if_type:CHA_LR_IF_TYPE, random_id:int,
                 timestamp:int, packets:list[int], adc_config_code:int
                 ):
        self.hdr = CHA_PROTO_HDR(if_type, 
                                 CHA_MSG_TYPE.STREAM_START, 
                                 rand=random_id
                                 )
        self.timestamp = timestamp
        self.packets = packets
        self.adc_config_code = adc_config_code

    def __bytes__(self):
        mask = [0]*STREAM_START_REQUEST.BITMASK_SZ_32
        for packet_n in self.packets: bit_set(mask, packet_n)

        payload_bytes = struct.pack(STREAM_START_REQUEST.DATASTRUCT, 
                           self.timestamp,
                           *mask,
                           self.adc_config_code
                           )
        self.hdr.chunk_sz = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes
    
class STREAM_FEEDBACK_REQUEST(CHA_REQUEST):
    BITMASK_SZ_32 = 13
    DATASTRUCT = f'<L{BITMASK_SZ_32}L'

    def __init__(self, if_type:CHA_LR_IF_TYPE, random_id:int,
                 timestamp:int, packets:list[int]
                 ):
        self.hdr = CHA_PROTO_HDR(if_type, 
                                 CHA_MSG_TYPE.STREAM_FB, 
                                 rand=random_id
                                 )
        self.packets = packets
        self.timestamp = timestamp

    def __bytes__(self):
        mask = [0]*STREAM_FEEDBACK_REQUEST.BITMASK_SZ_32
        for packet_n in self.packets: bit_set(mask, packet_n)

        payload_bytes = struct.pack(STREAM_FEEDBACK_REQUEST.DATASTRUCT,
                                    self.timestamp,
                                    *mask
                                    )
        
        self.hdr.chunk_sz = len(payload_bytes)
        return bytes(self.hdr) + payload_bytes
    
class STREAM_STOP_REQUEST(CHA_REQUEST):
    def __init__(self, if_type:CHA_LR_IF_TYPE, random_id:int):
        self.hdr = CHA_PROTO_HDR(if_type, 
                                    CHA_MSG_TYPE.STREAM_STOP, 
                                    rand=random_id
                                    )


'''
RESPONSES
'''

class STREAM_START_RESPONSE(CHA_RESPONSE):
    pass

class STREAM_STOP_RESPONSE(CHA_RESPONSE):
    pass

class STREAM_DATA_RESPONSE(CHA_RESPONSE):

    def __init__(self, hdr:CHA_PROTO_HDR, payload_bytes:bytes):
        super().__init__(hdr)
        if self.hdr.chunk_n == 0: #first chunk contains data hdr
            self.node_id = payload_bytes[0]
            unpacker = bit_unpack(payload_bytes[1])
            next(unpacker)
            self.packet_n = unpacker.send(3)
            self.payload_present = bool(unpacker.send(1))
            self.err_code = unpacker.send(4)
            if self.payload_present: 
                self.hdr.wait_next_chunk = True
                self.payload = payload_bytes[4:]
        else:
            self.payload = payload_bytes

    def concat_payloads(self, second_chunk:'STREAM_DATA_RESPONSE'):
        self.payload += second_chunk.payload

__all__ = [
    'STREAM_START_REQUEST',
    'STREAM_FEEDBACK_REQUEST',
    'STREAM_STOP_REQUEST',
    'STREAM_START_RESPONSE',
    'STREAM_STOP_RESPONSE',
    'STREAM_DATA_RESPONSE'
]