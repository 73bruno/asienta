<div align="center">

<img src="asienta/web/favicon.svg" width="72" alt="">

# Asienta

Lee facturas de proveedores con un modelo de IA y las convierte en asientos<br>
para **Sage 50, ContaPlus, A3, Holded, Xero, QuickBooks** o CSV.

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Dependencias](https://img.shields.io/badge/dependencias-0-16A34A)
![Licencia](https://img.shields.io/badge/licencia-MIT-4F46E5)

<img src="docs/media/demo.gif" width="100%" alt="Un ticket llega por correo, se lee, se corrige un NIF en un clic, se reparte por cuentas y se exporta">

<sub>La app de demo, con datos ficticios · [MP4](docs/media/demo.mp4) · [English](README.md)</sub>

</div>

## Qué hace

1. **Recoge las facturas** de un buzón de correo, una carpeta vigilada, arrastrando, con la cámara del móvil o por API.
2. **Lee cada una** con el modelo de IA que elijas y la pasa a un esquema fijo: proveedor, NIF, número, fecha, líneas, IVA.
3. **Propone el asiento** a partir de tu contabilidad: qué proveedor, qué cuenta de gasto, cómo repartir las líneas, con qué fecha.
4. **Lo comprueba**: dígito de control del NIF, sumas, IVA según el tipo, duplicados, fechas de un trimestre con el IVA ya presentado.
5. **Tú apruebas** y genera un fichero que tu programa de contabilidad importa.

El modelo solo hace el paso 2. El resto es código normal: cada propuesta se puede explicar y probar, y el modelo se puede cambiar.

## Funciona con

| Programa de contabilidad | Modelos de IA | Tu contabilidad, leída de | Las facturas entran por |
|---|---|---|---|
| Sage 50 · importación XDIARIO | Google Gemini | CSV exportados (cualquier programa) | Correo (IMAP) |
| Sage 50 · importador Excel *(beta)* | Anthropic Claude | Exportación de cuentas de Sage 50 / ContaPlus | Carpeta vigilada |
| ContaPlus *(beta)* | OpenAI | Sage 50 en vivo, solo lectura (SQL Server) | Arrastrar y soltar |
| a3ASESOR eco / con *(beta)* | Cualquier API compatible con OpenAI: Mistral, OpenRouter, Azure… | | Cámara del móvil |
| Holded *(beta)* | Locales: Ollama, LM Studio, vLLM | | API HTTP |
| Xero · QuickBooks Online *(beta)* | | | |
| CSV · JSON | | | |

Los formatos *beta* siguen el formato de importación publicado por cada programa y tienen tests, pero aún no se han importado en el programa real. Prueba primero en una empresa de pruebas y [cuenta qué tal](https://github.com/73bruno/asienta/issues/new?template=exporter.md).

## Prueba la demo

```bash
pip install "git+https://github.com/73bruno/asienta"
asienta --demo
```

Un negocio ficticio con su contabilidad y un mes de facturas, en `http://localhost:8760`. Sin clave de IA. Pulsa **Load samples**, o **Mailbox › Send a test email** para ver llegar la foto de un ticket reenviado. El idioma se cambia abajo a la izquierda.

## Úsalo con tus datos

```bash
asienta init             # crea config.ini y una carpeta ledger/ con CSV de ejemplo
asienta check            # prueba el modelo de IA y la conexión con la contabilidad
asienta                  # http://localhost:8760
```

Todo se elige en `config.ini`:

```ini
[reader]
provider = gemini              ; gemini | claude | openai | ollama
model = gemini-3.8-flash       ; clave en GEMINI_API_KEY, ANTHROPIC_API_KEY u OPENAI_API_KEY

[ledger]
source = csv                   ; csv | sage50 (en vivo, solo lectura)

[export]
format = sage50                ; sage50 | contaplus | sage50xls | a3 | holded | xero | quickbooks | csv | json

[inbox]
folder = ~/Dropbox/Facturas    ; opcional; [mailbox] para un buzón IMAP
```

Para usar un modelo local, sin que las facturas salgan de tu red:

```ini
[reader]
provider = ollama
model = llama3.2-vision
```

Guías (en inglés): [modelos de IA](docs/ai-models.md) · [contabilidad](docs/ledger.md) · [exportadores](docs/exporters.md) · [correo](docs/mailbox.md) · [carpeta y API](docs/api.md) · [instalación](docs/deploy.md) · [personalizar](docs/customizing.md)

## Añade lo tuyo

Lectores, fuentes de contabilidad y exportadores son clases pequeñas registradas en un diccionario. En [extending](docs/extending.md) hay un exportador completo de unas 15 líneas; al registrarlo, los tests existentes lo prueban con todas las facturas de la demo.

## Cómo decide

- **Proveedor**: por NIF en tu contabilidad y, si no, por nombre. Si lo eliges a mano una vez, lo recuerda.
- **Cuenta**: a la que más han ido este año las facturas de ese proveedor, con el motivo a la vista.
- **Reparto**: el modelo etiqueta cada línea con una categoría (comida, bebidas, limpieza… tu propia lista) y cada categoría tiene su cuenta. El vino de una factura de comida va a bebidas.
- **Fecha**: la de la factura, salvo que ese trimestre ya tenga el IVA presentado; entonces pasa al primer día abierto.
- **Comprobaciones**: un NIF que no pasa el dígito de control se corrige en un clic con el de tu contabilidad. Totales, IVA, fechas futuras, duplicados, retenciones y posibles inmovilizados se avisan antes de aprobar.

Para comparar modelos con tus facturas, `asienta bench` cuenta los datos que cada uno lee mal y cuántos de esos no avisó ninguna comprobación.

## Rendimiento

| | |
|---|---|
| Lectura con IA | ~5 s por factura con Gemini Flash, tres a la vez, en segundo plano |
| Reglas y comprobaciones | ~2 ms por factura |
| Exportar | 1.000 facturas en menos de 0,25 s |
| Memoria / arranque | 26 MB / menos de 0,5 s |
| Paquete | 240 KB, sin dependencias: Python estándar, SQLite, JavaScript sin compilar |

Medido en un Apple M1; `python scripts/speed.py` lo mide en tu equipo. Solo cuesta dinero la lectura con IA: menos de un céntimo por factura con Gemini Flash, nada con un modelo local.

## A tener en cuenta

- La parte fiscal es española (NIF/NIE/CIF, IVA, IRPF, recargo de equivalencia). Otros países necesitan su propio módulo; el resto no depende de ello.
- Lee tu contabilidad y nunca escribe en ella. Escucha solo en localhost; para lo demás pide token de acceso o Tailscale.
- La interfaz está en español e inglés, en claro y oscuro, y admite tu nombre, color y logo.

## Licencia

[MIT](LICENSE): libre para cualquier uso, también comercial. Se agradecen contribuciones, sobre todo exportadores para otros programas y experiencias de importaciones reales. Ver [CONTRIBUTING.md](CONTRIBUTING.md).

<sub>Sage 50, ContaPlus, a3ASESOR, Holded, Xero, QuickBooks y los proveedores de IA citados son marcas de sus dueños. Este proyecto no tiene relación con ninguno de ellos.</sub>
