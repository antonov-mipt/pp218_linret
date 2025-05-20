def bit_pack():
    result = 0
    bitctr = 0
    while True:
        next_vals = yield result
        if next_vals is None: break
        next_val, n_bits = next_vals
        next_val = int(next_val)
        #if type(next_val) != int: raise RuntimeError("pack type must be int")
        if next_val < 0: raise RuntimeError("pack val must be non-negative")
        if next_val >= (1<<n_bits): raise RuntimeError("pack type must fit bisize")
        result += next_val<<bitctr
        bitctr += n_bits

def bit_unpack(val):
    retval = None
    while True:
        bitsize = yield retval
        retval = (val)&((1<<bitsize)-1)
        val = val >> bitsize

def string_pack(inpt, n_bytes):
    byte_str = inpt.encode("utf-8")
    strlen = len(byte_str)
    if strlen > n_bytes: return byte_str[:n_bytes]
    elif strlen < n_bytes: return byte_str + b'\0'*(n_bytes-strlen)
    else: return byte_str

def CS_TEMPERATURE(inpt):
    inpt = int(inpt)
    if inpt > 127: inpt = 127
    if inpt < -128: inpt -128
    return inpt

def CS_HUMIDITY(inpt):
    inpt = int(inpt)
    if inpt > 100: inpt = 100
    if inpt < 0: inpt = 0
    return inpt

def CS_BAT_VOLTAGE(inpt):
    val = int(inpt * 10)
    if val > 255: val = 55
    if val < 0: val = 0
    return val

