#!/usr/bin/env python3
"""
avell-fan-ctl — Monitor de EC para Avell A52 ION (base Clevo)
Acesso direto ao EC via porta I/O (inb/outb), portas 0x62/0x66.
Requer: pip install portio psutil | execucao como root

Offsets validados empiricamente em 2026-05-03:
  REG_CPU_TEMP    = 0xC8  (confirmado: bate com turbostat ~92-96C sob carga)
  REG_FAN1_RPM_HI = 0xD0  (confirmado: formula 2156220/raw16 = RPM real)
  REG_FAN1_RPM_LO = 0xD1
  REG_FAN1_DUTY   = 0xCE  (aceita escrita mas EC sobrescreve - firmware soberano)

LIMITACAO: EC deste hardware nao expoe controle de duty via porta I/O padrao.
O script funciona como monitor preciso (status/monitor) e loga dados termicos.

Autor: Leandro Ferreira da Silva
Host:  leandrofds15-A52-ION
Data:  2026-05-03
"""

import time
import sys
import signal
import argparse
import logging
from typing import Optional

try:
    import portio
except ImportError:
    sys.exit("[ERRO] Instale portio: pip install portio")

try:
    import psutil
except ImportError:
    sys.exit("[ERRO] Instale psutil: pip install psutil")

EC_SC        = 0x66
EC_DATA      = 0x62
EC_IBF       = 0x02
EC_OBF       = 0x01
EC_CMD_READ  = 0x80
EC_CMD_WRITE = 0x81

REG_FAN1_DUTY   = 0xCE
REG_FAN1_RPM_HI = 0xD0
REG_FAN1_RPM_LO = 0xD1
REG_CPU_TEMP    = 0xC8

PROFILES = {
    "silent":      [(0,35,0),(35,50,20),(50,65,40),(65,75,60),(75,85,80),(85,999,100)],
    "balanced":    [(0,40,0),(40,55,30),(55,70,55),(70,80,75),(80,90,90),(90,999,100)],
    "performance": [(0,45,30),(45,60,50),(60,72,70),(72,82,85),(82,999,100)],
    "auto": [],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/avell-fan-ctl.log"),
    ]
)
log = logging.getLogger("avell-fan-ctl")


def _ec_wait_ibf():
    for _ in range(10000):
        if not (portio.inb(EC_SC) & EC_IBF): return
    raise TimeoutError("EC IBF timeout")

def _ec_wait_obf():
    for _ in range(10000):
        if portio.inb(EC_SC) & EC_OBF: return
    raise TimeoutError("EC OBF timeout")

def ec_read(reg: int) -> int:
    _ec_wait_ibf()
    portio.outb(EC_CMD_READ, EC_SC)
    _ec_wait_ibf()
    portio.outb(reg, EC_DATA)
    _ec_wait_obf()
    return portio.inb(EC_DATA)

def ec_write(reg: int, value: int):
    _ec_wait_ibf()
    portio.outb(EC_CMD_WRITE, EC_SC)
    _ec_wait_ibf()
    portio.outb(reg, EC_DATA)
    _ec_wait_ibf()
    portio.outb(value & 0xFF, EC_DATA)

def ec_set_fan_auto():
    ec_write(REG_FAN1_DUTY, 0x00)
    log.info("Fan -> modo AUTO (EC controla)")

def ec_set_fan_duty(percent: int):
    percent = max(0, min(100, percent))
    raw = int(percent * 255 / 100)
    ec_write(REG_FAN1_DUTY, raw)
    log.info(f"Fan duty -> {percent}% (raw=0x{raw:02X}) [AVISO: EC pode sobrescrever]")

def ec_get_cpu_temp() -> int:
    try:
        val = ec_read(REG_CPU_TEMP)
        if 10 < val < 120:
            return val
    except Exception:
        pass
    temps = psutil.sensors_temperatures()
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
        if key in temps:
            return int(max(e.current for e in temps[key]))
    return 0

def get_rpm() -> Optional[int]:
    try:
        hi = ec_read(REG_FAN1_RPM_HI)
        lo = ec_read(REG_FAN1_RPM_LO)
        raw = (hi << 8) | lo
        if raw == 0 or raw == 0xFFFF: return None
        return int(2156220 / raw)
    except Exception:
        return None

def duty_for_temp(temp: int, profile: list) -> int:
    for (t_lo, t_hi, duty) in profile:
        if t_lo <= temp < t_hi: return duty
    return 100


_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Encerrando...")
    _running = False

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def run_monitor(interval: float = 2.0):
    if portio.ioperm(EC_DATA, 1, 1) or portio.ioperm(EC_SC, 1, 1):
        sys.exit("[ERRO] ioperm falhou - execute como root")
    log.info(f"Monitor ativo - intervalo: {interval}s | Ctrl+C para sair")
    while _running:
        try:
            temp = ec_get_cpu_temp()
            rpm  = get_rpm()
            log.info(f"CPU={temp}\u00b0C | fan={rpm if rpm else 'N/A'} RPM")
        except Exception as e:
            log.warning(f"Erro: {e}")
        time.sleep(interval)
    portio.ioperm(EC_DATA, 1, 0)
    portio.ioperm(EC_SC, 1, 0)


def run_daemon(profile_name: str, interval: float = 2.0):
    if profile_name == "auto":
        log.info("Perfil auto - monitor puro ativo.")
        run_monitor(interval)
        return
    profile = PROFILES[profile_name]
    log.info(f"Daemon - perfil: {profile_name} [AVISO: duty pode nao ser efetivo neste hardware]")
    if portio.ioperm(EC_DATA, 1, 1) or portio.ioperm(EC_SC, 1, 1):
        sys.exit("[ERRO] ioperm falhou - execute como root")
    last_duty = -1
    while _running:
        try:
            temp = ec_get_cpu_temp()
            duty = duty_for_temp(temp, profile)
            rpm  = get_rpm()
            if duty != last_duty:
                ec_set_fan_duty(duty)
                last_duty = duty
            log.info(f"CPU={temp}\u00b0C | duty={duty}% | fan={rpm if rpm else 'N/A'} RPM")
        except Exception as e:
            log.warning(f"Erro: {e}")
        time.sleep(interval)
    portio.ioperm(EC_DATA, 1, 0)
    portio.ioperm(EC_SC, 1, 0)


def main():
    parser = argparse.ArgumentParser(
        description="avell-fan-ctl - Monitor EC para Avell A52 ION"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Leitura unica: temperatura e RPM")

    p_mon = sub.add_parser("monitor", help="Monitor continuo de temperatura e RPM")
    p_mon.add_argument("--interval", type=float, default=2.0)

    p_daemon = sub.add_parser("daemon", help="Daemon com perfil de curva")
    p_daemon.add_argument("--profile", choices=PROFILES.keys(), default="auto")
    p_daemon.add_argument("--interval", type=float, default=2.0)

    p_set = sub.add_parser("set", help="Tenta definir duty (pode ser sobrescrito pelo EC)")
    p_set.add_argument("percent", type=int)

    sub.add_parser("auto", help="Envia comando auto ao EC")

    args = parser.parse_args()

    if portio.ioperm(EC_DATA, 1, 1) != 0 or portio.ioperm(EC_SC, 1, 1) != 0:
        sys.exit("[ERRO] ioperm falhou - execute como root")

    if args.cmd == "status":
        temp = ec_get_cpu_temp()
        rpm  = get_rpm()
        print(f"CPU Temp : {temp}\u00b0C")
        print(f"Fan RPM  : {rpm if rpm else 'N/A'}")
        portio.ioperm(EC_DATA, 1, 0)
        portio.ioperm(EC_SC, 1, 0)
    elif args.cmd == "monitor":
        run_monitor(args.interval)
    elif args.cmd == "daemon":
        run_daemon(args.profile, args.interval)
    elif args.cmd == "set":
        ec_set_fan_duty(args.percent)
        portio.ioperm(EC_DATA, 1, 0)
        portio.ioperm(EC_SC, 1, 0)
    elif args.cmd == "auto":
        ec_set_fan_auto()
        portio.ioperm(EC_DATA, 1, 0)
        portio.ioperm(EC_SC, 1, 0)


if __name__ == "__main__":
    main()
