# Redragon RGB

Configura i LED RGB del mouse **Redragon M711 Cobra** e della tastiera **Redragon K556**
su Linux, con un'interfaccia GTK4 / libadwaita nativa per GNOME e una CLI per script.

*Linux RGB lighting control for the Redragon M711 Cobra mouse (`04d9:fc30`) and K556 keyboard
(`320f:5000`, `0c45:5004`) — GTK4/libadwaita GUI + CLI, no vendor software needed.*

| Dispositivo | USB ID | Stato |
|---|---|---|
| M711 Cobra | `04d9:fc30` | testato |
| M711-FPS-1 | `04d9:fc62` | non testato |
| K556 (EVision) | `320f:5000` | in test |
| K556 (SONiX) | `0c45:5004` | non testato |

## Funzionalità

- Una scheda per dispositivo (Mouse / Tastiera) con anteprima animata
- Tastiera: statico, respiro, onda, arcobaleno verticale, cerchi arcobaleno, uragano, accumulo,
  cielo stellato, scanner, increspatura, linea reattiva — con colore singolo o multicolore e direzione
- Mouse: statico, respiro, lampeggio, arcobaleno, respiro arcobaleno, onda, reattivo, spento
- Selettore colore + palette rapida
- Velocità e luminosità regolabili
- Anteprima animata dell'effetto
- Applicazione in tempo reale (opzionale) e salvataggio dell'ultima configurazione
- Le impostazioni vengono scritte nella memoria del mouse (tutti e 5 i profili), quindi restano anche dopo il riavvio o su altri PC

## Requisiti

Ubuntu 24.04+ / qualsiasi distro con GTK4 e libadwaita ≥ 1.5:

```sh
sudo apt install python3-gi gir1.2-adw-1 libusb-1.0-0
```

## Installazione

```sh
git clone https://github.com/codingkoala/redragon-rgb.git
cd redragon-rgb
sudo ./install-udev.sh   # una volta sola: permessi USB/hidraw per l'utente
./install.sh             # launcher in ~/.local/bin + voce nel menu applicazioni
```

Dopo la regola udev scollega e ricollega i dispositivi. Per provarlo senza installare:
`python3 -m redragon_rgb`.

## CLI

```sh
redragon-rgb-cli list
redragon-rgb-cli mouse static -c "#00e5ff" -b 3
redragon-rgb-cli mouse breathing -c ff1e3c -s 5
redragon-rgb-cli keyboard wave -m -s 4 -d right
redragon-rgb-cli keyboard static -c 2f6bff -b 4
redragon-rgb-cli keyboard off
redragon-rgb-cli restore        # riapplica le ultime impostazioni di tutti i dispositivi
```

## Come funziona

### Mouse

Il mouse si controlla con trasferimenti di controllo USB (HID `SET_REPORT`, report `0x02`)
sull'interfaccia vendor n. 2, tramite libusb caricata con `ctypes`: nessuna dipendenza pip.
hidraw non si può usare perché il descrittore del mouse non dichiara feature report.

| Frame | Significato |
|---|---|
| `02 F5 00` | sblocco (apre ogni sequenza) |
| `02 F3 <addr> <len> 00 00 00 <dati>` | scrittura |
| `02 F1 02 04` | applica |
| `02 F5 01` | blocco (chiude ogni sequenza: obbligatorio) |

LED del profilo *n* (0–4): `0x0449 + 8n` → `R, G, B, modo1, velocità, modo2`;
luminosità: `0x044F + 8n`. Colore e modo vengono sempre scritti insieme: scrivere solo
il colore mentre è attivo un effetto senza colore blocca l'animazione.

Il protocollo è documentato grazie a
[dokutan/mouse_m908](https://github.com/dokutan/mouse_m908),
[OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) e
[SK2674/m711-port](https://github.com/SK2674/m711-port), che ha misurato sull'hardware
il trasporto e le trappole del firmware.

### Tastiera K556

Pacchetti di output HID da 64 byte (report `0x04`) sull'interfaccia vendor (usage page `0xFF1C`)
via hidraw, con checksum dei byte 3–63 e risposta della tastiera a ogni pacchetto.
Ogni comando è racchiuso tra `begin` (`0x01`) ed `end` (`0x02`); il parametro 0 imposta
modalità, luminosità (0–4), velocità (5 lenta → 0 veloce), direzione, flag multicolore e RGB.

I codici modalità differiscono tra le revisioni del firmware: vengono esposti solo quelli su cui
concordano il driver EVision di OpenRGB e il controller K556 misurato sull'hardware da
[syndicalt/openrgb-reddragonk556-controller](https://github.com/syndicalt/openrgb-reddragonk556-controller).
Per mappare gli altri: `redragon-rgb-cli probe-keyboard 0x04`.

## Roadmap

- [x] Tastiera K556 (modalità)
- [ ] K556: colori per singolo tasto
- [ ] Lettura dello stato attuale dal mouse
- [ ] Selezione per profilo e DPI

## Licenza

GPL-3.0-or-later
