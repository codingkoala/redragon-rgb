# Cobra RGB

Configura i LED RGB del mouse **Redragon M711 Cobra** su Linux, con un'interfaccia
GTK4 / libadwaita nativa per GNOME e una CLI per script.

*Linux RGB lighting control for the Redragon M711 Cobra (USB `04d9:fc30`) — GTK4/libadwaita GUI + CLI, no vendor software needed.*

## Funzionalità

- Effetti: statico, respiro, lampeggio, arcobaleno, respiro arcobaleno, onda, reattivo, spento
- Selettore colore + palette rapida
- Velocità (1–8) e luminosità (1–3)
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
git clone https://github.com/codingkoala/cobra-rgb.git
cd cobra-rgb
sudo ./install-udev.sh   # una volta sola: permessi USB per l'utente
./install.sh             # launcher in ~/.local/bin + voce nel menu applicazioni
```

Dopo la regola udev scollega e ricollega il mouse. Per provarlo senza installare:
`python3 -m cobra_rgb`.

## CLI

```sh
cobra-rgb-cli list
cobra-rgb-cli set static -c "#00e5ff" -b 3
cobra-rgb-cli set breathing -c ff1e3c -s 5
cobra-rgb-cli set wave -s 8
cobra-rgb-cli set off
cobra-rgb-cli restore        # riapplica l'ultima configurazione salvata
```

## Come funziona

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

## Roadmap

- [ ] Supporto tastiere Redragon con controller EVision (`320f:5000`)
- [ ] Lettura dello stato attuale dal mouse
- [ ] Selezione per profilo e DPI

## Licenza

GPL-3.0-or-later
