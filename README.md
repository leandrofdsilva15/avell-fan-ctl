# avell-fan-ctl

Monitor de EC e tentativa de controle de ventoinha para **Avell A52 ION** (base Clevo) no Linux.  
Acessa o EC (Embedded Controller) via porta I/O (`inb`/`outb`, portas `0x62`/`0x66`).

## Status dos offsets (validado 2026-05-03)

| Registro | Offset | Status | Observação |
|---|---|---|---|
| `REG_CPU_TEMP` | `0xC8` | ✅ Validado | Bate com turbostat (~92–96°C sob carga) |
| `REG_FAN1_RPM_HI` | `0xD0` | ✅ Validado | Fórmula `2156220/raw16` retorna RPM real |
| `REG_FAN1_RPM_LO` | `0xD1` | ✅ Validado | Par com `0xD0` |
| `REG_FAN1_DUTY` | `0xCE` | ⚠️ Aceita escrita | EC sobrescreve — firmware soberano |

## Limitação conhecida

O EC deste hardware não expõe controle de duty via porta I/O padrão Clevo.  
Todos os 7 candidatos testados (`0xCE`, `0xC2`, `0xC4`, `0x63`, `0x6C`, `0x65`) aceitam escrita  
mas o RPM não responde — o firmware mantém controle soberano da ventoinha.  
O script funciona plenamente como **monitor de temperatura e RPM em tempo real**.

## Hardware validado

| Campo | Valor |
|---|---|
| Host | `leandrofds15-A52-ION` |
| OS | Zorin OS (Ubuntu 24.04 Noble) |
| EC FFAN (MMIO) | `0xFE410460` |
| Range FFAN observado | `0x0` – `0x9` (EC autônomo) |
| CPU temp sob carga | ~92–96°C |
| PkgWatt estável | ~45 W |
| Driver NVIDIA | 595.58.03 |

## Instalação

```bash
git clone https://github.com/leandrofdsilva15/avell-fan-ctl.git
cd avell-fan-ctl
python3 -m venv venv
venv/bin/pip install portio psutil
```

## Uso

```bash
# Leitura única
sudo venv/bin/python3 avell_fan_ctl.py status

# Monitor contínuo (Ctrl+C para sair)
sudo venv/bin/python3 avell_fan_ctl.py monitor --interval 2

# Daemon com log (perfil auto = monitor puro)
sudo venv/bin/python3 avell_fan_ctl.py daemon --profile auto --interval 2

# Sudo sem senha (recomendado para watch/monitor)
echo "$USER ALL=(ALL) NOPASSWD: $(pwd)/venv/bin/python3 $(pwd)/avell_fan_ctl.py *" \
  | sudo tee /etc/sudoers.d/avell-fan-ctl
```

## Referências

- [PyECClevo](https://github.com/F-19-F/PyECClevo)
- [clevo-fan-control](https://github.com/agramian/clevo-fan-control)
- [clevo-indicator](https://github.com/SkyLandTW/clevo-indicator)
- DSDT analisado: `FFAN` offset `0x460`, base EC `0xFE410000`
