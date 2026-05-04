# avell-fan-ctl

Controle ativo de ventoinha para **Avell A52 ION** (base Clevo) no Linux.  
Acessa o EC (Embedded Controller) via porta I/O (`inb`/`outb`, portas `0x62`/`0x66`).

## Hardware validado

| Campo | Valor |
|---|---|
| Host | `leandrofds15-A52-ION` |
| EC FFAN (MMIO) | `0xFE410460` |
| Range FFAN observado | `0x0` – `0x9` |
| CPU temp sob carga | ~93–96°C |
| PkgWatt estável | ~45 W |
| OS | Zorin OS (Ubuntu 24.04 Noble) |
| Driver NVIDIA | 595.58.03 |

## Instalação

```bash
# Clonar o repositório
git clone https://github.com/leandrofdsilva15/avell-fan-ctl.git
cd avell-fan-ctl

# Criar venv e instalar dependências
python3 -m venv venv
venv/bin/pip install portio psutil
```

## Uso

```bash
# Status atual (temperatura + RPM)
sudo venv/bin/python3 avell_fan_ctl.py status

# Daemon com perfil
sudo venv/bin/python3 avell_fan_ctl.py daemon --profile balanced --interval 2

# Perfis: silent | balanced | performance | auto

# Forçar duty manual (0-100%)
sudo venv/bin/python3 avell_fan_ctl.py set 80

# Devolver controle ao EC
sudo venv/bin/python3 avell_fan_ctl.py auto
```

## Perfis

| Perfil | Foco |
|---|---|
| `silent` | Silêncio máximo, aceita temperatura mais alta |
| `balanced` | Equilíbrio padrão (recomendado) |
| `performance` | Fan ativo desde cedo, temperatura mais baixa |
| `auto` | Delega 100% ao EC (comportamento padrão do firmware) |

## Registros EC mapeados

| Registro | Offset | Descrição |
|---|---|---|
| `REG_FAN1_DUTY` | `0xCE` | Duty cycle (0x00=auto, 0x01–0xFF=manual) |
| `REG_FAN1_RPM_HI` | `0xD0` | RPM byte alto |
| `REG_FAN1_RPM_LO` | `0xD1` | RPM byte baixo |
| `REG_CPU_TEMP` | `0x07` | Temperatura CPU (°C direto) |

> **Nota:** Offsets são padrão Clevo. Valide com `status` antes de ativar o daemon.

## Validação rápida

```bash
# 1. Testar leitura
sudo venv/bin/python3 avell_fan_ctl.py status

# 2. Testar escrita
sudo venv/bin/python3 avell_fan_ctl.py set 50
sleep 3 && sudo venv/bin/python3 avell_fan_ctl.py status

# 3. Restaurar
sudo venv/bin/python3 avell_fan_ctl.py auto
```

## Instalação como serviço systemd

```bash
sudo mkdir -p /opt/avell-fan-ctl
sudo cp avell_fan_ctl.py /opt/avell-fan-ctl/
sudo cp avell-fan-ctl.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avell-fan-ctl
sudo journalctl -u avell-fan-ctl -f
```

## Riscos

- EC pode sobrescrever valores — daemon em loop de 2s compete com o firmware
- Offsets `0xCE`/`0xD0`/`0xD1`/`0x07` são padrão Clevo, validar empiricamente
- Signal handler restaura `auto` no SIGTERM/SIGINT
- Em `silent`: limite de 85°C → 100% duty em todos os perfis

## Referências

- [PyECClevo](https://github.com/F-19-F/PyECClevo)
- [clevo-fan-control](https://github.com/agramian/clevo-fan-control)
- [clevo-indicator](https://github.com/SkyLandTW/clevo-indicator)
