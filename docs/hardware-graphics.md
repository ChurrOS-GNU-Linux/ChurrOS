# Gráficos, GPU y laptops

## Drivers que incluyen las ediciones x86_64

Las ediciones de escritorio Niri y XFCE incluyen Mesa, los ICD Vulkan abiertos `vulkan-intel`, `vulkan-radeon` y `vulkan-nouveau`, y `vulkan-virtio` para máquinas virtuales. Los paquetes `lib32-*` permiten a aplicaciones Vulkan de 32 bits encontrar esos ICD en los escritorios Niri y XFCE. `linux-firmware` proporciona el conjunto de firmware que usa el kernel; el driver de kernel para Intel, AMD y Nouveau forma parte de Linux.

Para video Intel se incluyen `intel-media-driver` (iHD, generaciones Broadwell y posteriores) y `libva-intel-driver` (i965, hardware Intel anterior que ese driver soporta). Mesa proporciona el driver VA-API para AMD.

`switcheroo-control` proporciona la interfaz de detección de GPU dual y `switcherooctl` para aplicaciones compatibles. En XFCE también se instala `power-profiles-daemon`, que permite a Ajustes consultar/cambiar los perfiles de energía cuando el firmware del equipo los expone. Niri ya lo incluía.

## Lo que esto no garantiza

- Que todo modelo de laptop, conector externo, suspensión, brillo o cambio entre GPU funcione: hay que probar cada equipo y firmware.
- Que Nouveau sustituya al driver propietario de NVIDIA. Su rendimiento y compatibilidad varían por generación; algunas GPUs recientes requieren el controlador oficial para aceleración completa.
- La instalación automática del módulo propietario de NVIDIA. ChurrOS usa `linux-cachyos`; el proyecto no debe instalar un módulo DKMS sin headers compatibles con ese kernel. Por eso esta propuesta no añade el driver propietario ni afirma que los juegos/renderizados de NVIDIA estén cubiertos.
- Los paquetes x86_64 no aplican a Raspberry Pi/ARM ni a la edición i686.

## Diagnóstico para reportar una laptop

En una terminal, copia el resultado de estos comandos al [informe de hardware](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/new?template=hardware.yml):

```sh
lspci -nnk | grep -A3 -Ei 'VGA|3D|Display'
switcherooctl list
vulkaninfo --summary
vainfo
powerprofilesctl list
```

Si no funciona `vulkaninfo`, `vainfo` o `switcherooctl`, indícalo junto con fabricante/modelo de laptop, edición e ISO. También reporta si falla la pantalla externa, brillo, suspensión o reanudación. No publiques números de serie.

La inclusión de paquetes se verifica en CI; la compatibilidad visual y de energía aún requiere pruebas en equipos físicos.
