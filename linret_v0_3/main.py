import os, sys, psutil, signal, logging, coloredlogs, argparse
import core, iface_chassis, iface_cs, monitor, stream_proc, config
import nmea_true_time
from protocol.sn_emulator import *

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, required=True, help="Path to config file")
    parser.add_argument('-l', '--loglevel', type=int, default=3, choices=range(1, 6),
                        help="1=DEBUG, 2=INFO, 3=WARNING, 4=ERROR, 5=CRITICAL")

    
    args = parser.parse_args()

    logger = setup_logging(args.loglevel)
    logger.warning(f"Program start")
    program_params = config.PROGRAM_CONFIG(args.config)
    logger.warning(f'Using params: {program_params}')

    lock_flname = os.path.join(os.path.dirname(__file__), '/run/lock/linret.pid')
    if os.path.exists(lock_flname):
        with open(lock_flname, 'r') as f: lock_pid= int(f.read())
        if os.getpid() != lock_pid and lock_pid in psutil.pids():
            print("Linret already running! (PID %d)"%lock_pid)
            exit()
    with open(lock_flname, 'w') as f: f.write(str(os.getpid())) 


    true_time = nmea_true_time.TRUE_TIME(program_params.get_use_system_time())

    SN_EMULATOR(LR_NUM = program_params.get_lr_n())
    _mon = monitor.HTTP_MONITOR(true_time, program_params)
    _core = core.LINRET_CORE(program_params, true_time)
    _chassis = iface_chassis.IFACE_CHASSIS(program_params)
    _cs = iface_cs.IFACE_TO_CS(program_params)
    _stream = stream_proc.LINRET_STREAMREADER(program_params, true_time)

    _core.register_msg_handlres(
        _chassis.send_msg_to_chassis,
        _cs.send_msg_to_cs,
        _stream.send_msg_to_streamer,
        _mon.send_msg_to_mon
    )

    _chassis.register_msg_handlers(
        _core.send_msg_to_core,
        _stream.send_msg_to_streamer,
        _mon.send_msg_to_mon
    )

    _cs.register_msg_handlers(
        _core.send_msg_to_core,
        _mon.send_msg_to_mon
    )

    _stream.register_msg_handlres(
        _chassis.send_msg_to_chassis,
        _core.send_msg_to_core,
        _mon.send_msg_to_mon
    )

    _mon.register_msg_handlres(
        _core.send_msg_to_core
    )

    true_time.run()
    _chassis.run()
    _cs.run()
    _mon.run()
    _stream.run()

    def shutdown_signal(sig, frame): 
        logger.critical("Exit signal %d"%sig)
        _core.send_msg_to_core('shutdown')
        _chassis.send_msg_to_chassis('shutdown')
        _cs.send_msg_to_cs('shutdown')
        _mon.send_msg_to_mon('shutdown')
        _stream.send_msg_to_streamer('shutdown')

    signal.signal(signal.SIGINT, shutdown_signal)
    signal.signal(signal.SIGUSR1, shutdown_signal)
    signal.signal(signal.SIGUSR2, shutdown_signal)

    logger.info("Program started")
    _core.main_loop()
    logger.info("Program is stopping")

    _stream.join()
    _chassis.join()
    _cs.join()
    _mon.join()
    true_time.join()


def setup_logging(log_level_num):
    level_mapping = {
        1: logging.DEBUG,
        2: logging.INFO,
        3: logging.WARNING,
        4: logging.ERROR,
        5: logging.CRITICAL
    }

    log_level = level_mapping.get(log_level_num, 1)
    if log_level_num not in level_mapping:
        raise ValueError(f"Incorrect log level: {log_level_num}")
    

    logger = logging.getLogger('')
    logger.setLevel(log_level)
    logger.propagate = False
    fmt = "%(asctime)s %(message)s"
    coloredlogs.install(logger = logger, level = log_level, fmt = fmt)

    logging.getLogger('pymongo').setLevel(logging.WARNING) 
    logging.getLogger('gpsd').setLevel(logging.WARNING) 
    logger.warning(f'Log level: {log_level}')
    return logger


if __name__ == '__main__': 
    main()