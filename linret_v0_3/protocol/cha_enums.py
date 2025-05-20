from enum import IntEnum

class CHA_LR_IF_TYPE(IntEnum):
    INVALID = 0
    DRIVER = 1
    LOCAL = 2
    WIFI_0 = 3
    WIFI_1 = 4
    WIRED_0 = 5
    WIRED_1 = 6

class CHA_MSG_TYPE(IntEnum):
    STR_BIT = 0x08
    SRM_BIT = 0x10
    CTL_BIT = 0x20
    ACK_BIT = 0x80

    LR_HANDSHAKE_REQ        = 1
    LR_HANDSHAKE_ACK        = 1|ACK_BIT
    LR_DRIVER_STATUS_REQ    = 2
    LR_DRIVER_STATUS_ACK    = 2|ACK_BIT

    SRVC_LOG                = 0|ACK_BIT

    ECHO_REQ                = 6
    ECHO_ACK                = 6|ACK_BIT
    DISCOVERY               = 7|ACK_BIT

    STREAM_START            = STR_BIT|0
    STREAM_START_ACK        = STR_BIT|0|ACK_BIT
    STREAM_FB               = STR_BIT|1
    STREAM_DATA             = STR_BIT|2|ACK_BIT
    STREAM_STOP             = STR_BIT|3
    STREAM_STOP_ACK         = STR_BIT|3|ACK_BIT

    SRM_RUN_REQ             = SRM_BIT|0
    SRM_RUN_ACK             = SRM_BIT|0|ACK_BIT
    SRM_STOP_REQ            = SRM_BIT|1
    SRM_STOP_ACK            = SRM_BIT|1|ACK_BIT
    SRM_FAT_REQ             = SRM_BIT|2
    SRM_FAT_ACK             = SRM_BIT|2|ACK_BIT
    SRM_STAT_REQ            = SRM_BIT|3
    SRM_STAT_ACK            = SRM_BIT|3|ACK_BIT

    CNTL_REBOOT_REQ         = CTL_BIT|0
    CNTL_REBOOT_ACK         = CTL_BIT|0|ACK_BIT
    CNTL_STAT_REQ           = CTL_BIT|1
    CNTL_STAT_ACK           = CTL_BIT|1|ACK_BIT
    CNTL_NODES_BC_REQ       = CTL_BIT|2
    CNTL_NODES_BC_ACK       = CTL_BIT|2|ACK_BIT
    CNTL_SRM_REQ            = CTL_BIT|3
    CNTL_SRM_ACK            = CTL_BIT|3|ACK_BIT
    CNTL_SET_PARAMS         = CTL_BIT|4
    CNTL_SET_PARAMS_ACK     = CTL_BIT|4|ACK_BIT
    CNTL_CLK_SET_REQ        = CTL_BIT|5
    CNTL_CLK_SET_ACK        = CTL_BIT|5|ACK_BIT

class CHA_NAK_CODE(IntEnum):
    NO_ERROR = 0
    TRY_AGAIN = 1
    RESERVED2 = 2
    DEST_UNREACHABLE = 3
    UNKNOWN_CMD = 4

    SRM_CONN_TX_ERR = 5
    SRM_CONN_RX_ERR = 6
    SRM_CTL_ERR_GENERIC = 7
    SRM_CTL_ERR_PHASE = 8
    SRM_CTL_ERR_NO_GPS = 9
    SRM_CTL_ERR_NO_TIME = 10
    SRM_DATA_ERR = 11
    SRMS_ADC_PARAMS_MISMATCH = 12

    CTL_SRM_SCH_INVALID = 16
    CTL_SET_PPS_INVALID = 17
    CTL_SET_CLK_INVALID = 18
    CTL_SET_CLK_OUTOFPHASE = 19

class CHA_DEV_TYPE(IntEnum):
    INVALID = 0
    LINRET_LAND = 1
    LINRET_SEABAD = 2
    NODE_LAND = 3
    NODE_SEABED = 4
    BOTTOM_STATION = 5

class CHA_VCXO_TYPE(IntEnum):
    INVALID = 0
    NOT_ADJUSTABLE = 1
    COARSE = 2
    MXO37 = 3

class CHA_SYNC_SRC(IntEnum):
    INVALID = 0
    EXT1 = 1
    EXT2 = 2
    GPS = 3
    MCU = 4
    DISABLED = 5

class CHA_CONN_TYPE(IntEnum):
    INVALID = 0
    DISABPED = 1
    WIRED = 2
    WIRELESS = 4