# avell-fan-ctl

Controle ativo de ventoinhas para **Avell A52 ION** (chassi Tongfang GM5PG38 / firmware EC Uniwill) no Linux.

## Hardware

| Componente | Detalhe |
|---|---|
| Chassi / ODM | Tongfang GM5PG38 |
| Firmware EC / BIOS | Uniwill (ITE IT5570) |
| Driver Linux | `tuxedo-drivers` + `uniwill_wmi` |
| Kernel testado | 6.17.0-23-generic (Ubuntu Noble / Zorin OS 17) |

---

## Solução definitiva (TL;DR)

```bash
# 1. Adiciona repositório Tuxedo
curl -s https://deb.tuxedocomputers.com/0x54840598.pub.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/tuxedo-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/tuxedo-archive-keyring.gpg] \
https://deb.tuxedocomputers.com/ubuntu noble main" \
  | sudo tee /etc/apt/sources.list.d/tuxedo.list

# 2. Instala drivers e TCC
sudo apt update
sudo apt install tuxedo-drivers tuxedo-control-center

# 3. CRÍTICO: carrega uniwill_wmi antes do tccd
echo "uniwill_wmi" | sudo tee /etc/modules-load.d/uniwill.conf
sudo modprobe uniwill_wmi
sudo systemctl restart tccd

# 4. Verifica (deve mostrar "Detected 2 fans")
sudo journalctl -u tccd -n 5 --no-pager | grep -i fan

# 5. Abre interface gráfica de perfis
tuxedo-control-center
```

---

## Por que `uniwill_wmi` precisa ser carregado manualmente

O `tuxedo-drivers` instala o módulo mas **não o carrega automaticamente** porque o kernel carrega `asus_wmi` primeiro, que tenta (e falha) capturar o GUID `AMW0` do EC Uniwill. Sem `uniwill_wmi` ativo, o daemon `tccd` reporta:

```
FanControlWorker: onStart: Fan API not available
```

Com `uniwill_wmi` carregado antes do daemon:

```
FanControlWorker: initializeFanControl: tuxedo-io available
FanControlTuxedoIO: Enabling manual mode
FanControlWorker: initializeFanControl: Detected 2 fans
```

---

## Mapeamento do EC (engenharia reversa)

Realizado via `ec_probe dump` + análise de diff sob stress (`stress --cpu 12 --timeout 120s`).

### Registros de leitura (read-only efetivo)

| Registro | Função | Faixa observada |
|---|---|---|
| `0x4C` | Temperatura CPU (°C) | 39–81°C |
| `0x4F` | Temperatura secundária (°C) | ~33°C idle |
| `0x64–0x65` | Fan 1 período (big-endian) | Sobe sob carga |
| `0x6C–0x6D` | Fan 2 período (big-endian) | Sobe sob carga |
| `0x6A`, `0x6B` | Limite de temperatura fixo | 75°C (0x4B) |

### Registros ACPI / ECMG (SystemMemory `0xFE410000`)

| Símbolo | Offset | Bits | Função |
|---|---|---|---|
| `CPTM` | `0x43E` | 8 | Temperatura CPU |
| `VGAT` | `0x44F` | 8 | Temperatura GPU |
| `FFAN` | `0x460` | 4 | Fan field (leitura EC) |
| `SDAN` | `0x468` | 4 | Fan secundário |

> ⚠️ Writes diretos em `FFAN` via `/dev/mem` são sobrescritos pelo firmware EC imediatamente.

### Leitura via Python (monitoramento)

```python
import mmap, struct
ECMA = 0xFE410000
ECMS = 0x00010000
with open('/dev/mem', 'rb') as f:
    m = mmap.mmap(f.fileno(), ECMS, mmap.MAP_PRIVATE, mmap.PROT_READ, offset=ECMA)
    cpu_temp = m[0x43E]
    gpu_temp = m[0x44F]
    ffan     = m[0x460] & 0x0F
    print(f'CPU: {cpu_temp}°C | GPU: {gpu_temp}°C | FFAN: {ffan}/15')
    m.close()
```

---

## Perfis de fan (decodificados do DSDT)

Extraídos dos buffers `WTB*` no método `WMBB` do DSDT (`iasl -d dsdt.dat`).

| Buffer | Perfil | Fan liga a | Característica |
|---|---|---|---|
| `WTBE` | Balanced | 47°C | Padrão |
| `WTBV` | Turbo / Performance | 53°C | Fan liga mais tarde, limiar mais alto |
| `WTBZ` | Silent | 48°C | Curva suave |

---

## Ioctls de fan (tuxedo_io)

Definidas em `/usr/src/tuxedo-drivers-*/tuxedo_io/tuxedo_io_ioctl.h`:

```c
#define R_UW_FANSPEED          _IOR(MAGIC_READ_UW,  0x10, int32_t*)  // Fan 1 RPM
#define R_UW_FANSPEED2         _IOR(MAGIC_READ_UW,  0x11, int32_t*)  // Fan 2 RPM
#define R_UW_FAN_TEMP          _IOR(MAGIC_READ_UW,  0x12, int32_t*)  // Temp fan 1
#define R_UW_FAN_TEMP2         _IOR(MAGIC_READ_UW,  0x13, int32_t*)  // Temp fan 2
#define R_UW_FANS_OFF_AVAILABLE _IOR(MAGIC_READ_UW, 0x16, int32_t*)  // Suporte fan off
#define R_UW_FANS_MIN_SPEED    _IOR(MAGIC_READ_UW,  0x17, int32_t*)  // Velocidade mínima
#define W_UW_FANSPEED          _IOW(MAGIC_WRITE_UW, 0x10, int32_t*)  // Seta Fan 1
#define W_UW_FANSPEED2         _IOW(MAGIC_WRITE_UW, 0x11, int32_t*)  // Seta Fan 2
#define W_UW_FANAUTO           _IO(MAGIC_WRITE_UW,  0x14)            // Volta modo auto
```

---

## Processo de engenharia reversa (resumo)

1. `stress --cpu 12 --timeout 120s` + `ec_probe dump` antes/depois → diff de registros EC
2. Identificação de `0x4C` (temp), `0x64-0x65` / `0x6C-0x6D` (RPM fans)
3. Testes de escrita via `/dev/mem` → EC sobrescreve (modo auto bloqueado)
4. `acpidump -b -n DSDT` + `iasl -d` → análise DSDT completa
5. Localização de `CFAN=0x05`, `FFAN@0x460`, `CPTM@0x43E`, `VGAT@0x44F`
6. Testes via `acpi_call` em `WMBB`/`WMBC`/`SCMD` → sem controle direto
7. Identificação do ODM: **Tongfang GM5PG38 + firmware Uniwill** (não Tongfang puro)
8. Instalação `tuxedo-drivers` + descoberta do requisito `uniwill_wmi` pré-tccd
9. `modprobe uniwill_wmi && systemctl restart tccd` → **2 fans detectados**

---

## Referências

- [tuxedo-drivers](https://github.com/tuxedocomputers/tuxedo-drivers)
- [tuxedo-control-center](https://www.tuxedocomputers.com/en/Downloads-Drivers.tuxedo)
- [ec_probe (dell-fan-unlocking)](https://github.com/TomPWest/dell-fan-unlocking) — ferramenta usada para dump do EC
- [acpi_call](https://github.com/nix-community/acpi_call)
