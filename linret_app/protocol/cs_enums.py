from enum import IntEnum

class CS_PACKET_TYPE(IntEnum):
    ACK_NAK_RESPONSE = 1

    NODE_ID_LIST_REQUEST = 3
    NODE_ID_LIST_RESPONSE = 19

    SRM_STATE_REQUEST = 5
    SRM_STATE_RERESPONSE = 20

    LR_STATE_REQUEST = 6
    LR_STATE_REQPONSE = 21

    CHA_STATE_REQUEST = 7
    CHA_STATE_RESPONSE = 22

    CHA_LR_STATE_REQUEST = 8
    CHA_LR_STATE_RESPONSE = 23

    CMD_SET_CONFIG = 12
    CMD_ACQUISITION_CTL = 14

class CS_ACK_CODE(IntEnum):
    ACK = 1
    NAK = 2
    STALL = 3

class CS_DEV_TYPE(IntEnum):
    ANY = 0
    LR = 0x1 # CS_DEV_TYPE_REPEATER_BIT
    SRM = 0x2 #CS_DEV_TYPE_RECORDER_BIT
    CHA_LR = 0x21 #CS_DEV_TYPE_CHASSIS_BIT|CS_DEV_TYPE_REPEATER_BIT
    CHA_RN = 0x22 #CS_DEV_TYPE_CHASSIS_BIT|CS_DEV_TYPE_RECORDER_BIT
    CHA_LR_LAND = 0x61
    CHA_LR_SEA = 0xA1
    CHA_RN_LAND = 0x62
    CHA_RN_SEA = 0xA2

class CS_ADC_DR_CODE(IntEnum):
    DR_UNDEFINED = 0
    DR_2000 = 4
    DR_1000 = 5
    DR_500 = 6

class CS_ADC_CH_EN(IntEnum):
    ENABLED = 1
    DISABLED = 0

class CS_GAIN_CODE(IntEnum):
    GAIN_1 = 0
    GAIN_2 = 1
    GAIN_4 = 2
    GAIN_8 = 4
    GAIN_16 = 5
    GAIN_32 = 6
    GAIN_64 = 7

class CS_ACQ_STATE(IntEnum):
    IDLE = 0
    RUNNING = 0xFF

class CS_SRM_SYNC_STATE(IntEnum):
    NO_SYNC = 0
    SYNC = 0xFF

class CS_TEST_SIGNAL(IntEnum):
    NO_SIGNAL = 0
    PULSE = 1
    SENSITIVITY = 2
    SINE = 3

class CS_WIFI_CLIENT_STATE(IntEnum):
    LINKED = 0xFF
    NOT_LINKED = 0

class CS_BAT_STATE(IntEnum):
    PRESENT = 0x1
    DISCHARGING = 0x2
    CHARGING = 0x4